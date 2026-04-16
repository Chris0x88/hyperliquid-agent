"""Tests for LiquidationMonitorIterator (audit F6 — tiered cushion alerts)."""
from decimal import Decimal

import pytest

from daemon.context import TickContext
from daemon.iterators.liquidation_monitor import (
    LiquidationMonitorIterator,
    INFO_THRESHOLD,
    WARN_THRESHOLD,
    CRITICAL_REPEAT_TICKS,
    _classify,
)
from exchange.position_tracker import Position


def _ctx(positions=None, prices=None, tick=1):
    c = TickContext()
    c.tick_number = tick
    if positions:
        c.positions = positions
    if prices:
        c.prices = {k: Decimal(str(v)) for k, v in prices.items()}
    return c


def _long(inst, qty, entry, liq, lev=10):
    return Position(
        instrument=inst,
        net_qty=Decimal(str(qty)),
        avg_entry_price=Decimal(str(entry)),
        liquidation_price=Decimal(str(liq)),
        leverage=Decimal(str(lev)),
    )


def _short(inst, qty, entry, liq, lev=10):
    return Position(
        instrument=inst,
        net_qty=Decimal(str(-abs(qty))),
        avg_entry_price=Decimal(str(entry)),
        liquidation_price=Decimal(str(liq)),
        leverage=Decimal(str(lev)),
    )


class TestClassify:
    def test_safe(self):
        assert _classify(Decimal("0.30")) == "safe"
        assert _classify(INFO_THRESHOLD) == "safe"

    def test_warning_band(self):
        assert _classify(Decimal("0.04")) == "warning"
        assert _classify(WARN_THRESHOLD) == "warning"
        # Just below info threshold
        assert _classify(INFO_THRESHOLD - Decimal("0.001")) == "warning"

    def test_critical(self):
        assert _classify(Decimal("0.01")) == "critical"
        assert _classify(WARN_THRESHOLD - Decimal("0.001")) == "critical"
        assert _classify(Decimal("0")) == "critical"


class TestLongPosition:
    def test_safe_no_alert(self):
        it = LiquidationMonitorIterator()
        # mark=100, liq=70, cushion=(100-70)/100=30% → safe
        ctx = _ctx(positions=[_long("BTC", 1, 100, 70)], prices={"BTC": 100})
        it.tick(ctx)
        assert ctx.alerts == []

    def test_warning_alert_on_transition(self):
        it = LiquidationMonitorIterator()
        # mark=100, liq=96, cushion=4% → warning
        ctx = _ctx(positions=[_long("BTC", 1, 100, 96)], prices={"BTC": 100})
        it.tick(ctx)
        assert len(ctx.alerts) == 1
        a = ctx.alerts[0]
        assert a.severity == "warning"
        assert a.source == "liquidation_monitor"
        assert "BTC" in a.message
        assert "LONG" in a.message
        assert a.data["tier"] == "warning"
        assert 3.5 < a.data["cushion_pct"] < 4.5

    def test_critical_alert_on_transition(self):
        it = LiquidationMonitorIterator()
        # mark=100, liq=99, cushion=1% → critical
        ctx = _ctx(positions=[_long("BTC", 1, 100, 99)], prices={"BTC": 100})
        it.tick(ctx)
        assert len(ctx.alerts) == 1
        a = ctx.alerts[0]
        assert a.severity == "critical"
        assert "CRITICAL" in a.message
        assert a.data["tier"] == "critical"

    def test_no_repeat_alert_within_warning_tier(self):
        it = LiquidationMonitorIterator()
        positions = [_long("BTC", 1, 100, 96)]
        prices = {"BTC": 100}
        # First tick → alert
        ctx1 = _ctx(positions=positions, prices=prices, tick=1)
        it.tick(ctx1)
        assert len(ctx1.alerts) == 1
        # Second tick same tier → no alert
        ctx2 = _ctx(positions=positions, prices=prices, tick=2)
        it.tick(ctx2)
        assert ctx2.alerts == []

    def test_critical_repeats_after_n_ticks(self):
        it = LiquidationMonitorIterator()
        positions = [_long("BTC", 1, 100, 99)]
        prices = {"BTC": 100}
        # First tick → critical alert
        ctx1 = _ctx(positions=positions, prices=prices, tick=1)
        it.tick(ctx1)
        assert len(ctx1.alerts) == 1
        # Mid-window → no alert
        ctx_mid = _ctx(positions=positions, prices=prices, tick=5)
        it.tick(ctx_mid)
        assert ctx_mid.alerts == []
        # After CRITICAL_REPEAT_TICKS → alert again
        ctx_repeat = _ctx(positions=positions, prices=prices, tick=1 + CRITICAL_REPEAT_TICKS)
        it.tick(ctx_repeat)
        assert len(ctx_repeat.alerts) == 1
        assert ctx_repeat.alerts[0].severity == "critical"


class TestShortPosition:
    def test_safe(self):
        it = LiquidationMonitorIterator()
        # short: mark=100, liq=130, cushion=(130-100)/100=30% → safe
        ctx = _ctx(positions=[_short("BTC", 1, 100, 130)], prices={"BTC": 100})
        it.tick(ctx)
        assert ctx.alerts == []

    def test_warning(self):
        it = LiquidationMonitorIterator()
        # short: mark=100, liq=103, cushion=3% → warning
        ctx = _ctx(positions=[_short("BTC", 1, 100, 103)], prices={"BTC": 100})
        it.tick(ctx)
        assert len(ctx.alerts) == 1
        assert ctx.alerts[0].severity == "warning"
        assert "SHORT" in ctx.alerts[0].message

    def test_critical(self):
        it = LiquidationMonitorIterator()
        # short: mark=100, liq=101, cushion=1% → critical
        ctx = _ctx(positions=[_short("BTC", 1, 100, 101)], prices={"BTC": 100})
        it.tick(ctx)
        assert len(ctx.alerts) == 1
        assert ctx.alerts[0].severity == "critical"


class TestRecovery:
    def test_recovery_alert_warning_to_safe(self):
        it = LiquidationMonitorIterator()
        pos = [_long("BTC", 1, 100, 96)]
        # tick 1: warning (cushion=4%)
        ctx1 = _ctx(positions=pos, prices={"BTC": 100}, tick=1)
        it.tick(ctx1)
        assert ctx1.alerts[0].severity == "warning"
        # tick 2: price moved up, cushion now ~13% → safe
        ctx2 = _ctx(positions=pos, prices={"BTC": 110}, tick=2)
        it.tick(ctx2)
        assert len(ctx2.alerts) == 1
        assert ctx2.alerts[0].severity == "info"
        assert "RECOVERED" in ctx2.alerts[0].message

    def test_recovery_critical_to_safe(self):
        it = LiquidationMonitorIterator()
        pos = [_long("BTC", 1, 100, 99)]
        ctx1 = _ctx(positions=pos, prices={"BTC": 100}, tick=1)
        it.tick(ctx1)
        assert ctx1.alerts[0].severity == "critical"
        # Big rally
        ctx2 = _ctx(positions=pos, prices={"BTC": 130}, tick=2)
        it.tick(ctx2)
        assert ctx2.alerts[0].severity == "info"
        assert "RECOVERED" in ctx2.alerts[0].message


class TestMissingData:
    def test_missing_liq_price(self):
        it = LiquidationMonitorIterator()
        # No liquidation_price reported by exchange
        pos = _long("BTC", 1, 100, 0)  # liq=0
        ctx = _ctx(positions=[pos], prices={"BTC": 100})
        it.tick(ctx)
        assert ctx.alerts == []  # silently skipped

    def test_missing_mark_price(self):
        it = LiquidationMonitorIterator()
        ctx = _ctx(positions=[_long("BTC", 1, 100, 95)], prices={})  # no mark
        it.tick(ctx)
        assert ctx.alerts == []  # silently skipped

    def test_zero_qty_position(self):
        it = LiquidationMonitorIterator()
        pos = Position(
            instrument="BTC",
            net_qty=Decimal("0"),
            avg_entry_price=Decimal("100"),
            liquidation_price=Decimal("95"),
        )
        ctx = _ctx(positions=[pos], prices={"BTC": 100})
        it.tick(ctx)
        assert ctx.alerts == []


class TestStateCleanup:
    def test_closed_position_state_cleared(self):
        it = LiquidationMonitorIterator()
        # Tick 1: open warning position
        ctx1 = _ctx(
            positions=[_long("BTC", 1, 100, 96)],
            prices={"BTC": 100},
            tick=1,
        )
        it.tick(ctx1)
        assert "BTC" in it._last_tier
        # Tick 2: position gone
        ctx2 = _ctx(positions=[], prices={"BTC": 100}, tick=2)
        it.tick(ctx2)
        assert "BTC" not in it._last_tier

    def test_reopened_position_alerts_again(self):
        it = LiquidationMonitorIterator()
        pos = [_long("BTC", 1, 100, 96)]
        # Tick 1
        ctx1 = _ctx(positions=pos, prices={"BTC": 100}, tick=1)
        it.tick(ctx1)
        assert len(ctx1.alerts) == 1
        # Position closes
        ctx2 = _ctx(positions=[], prices={"BTC": 100}, tick=2)
        it.tick(ctx2)
        # Reopens at same tier — should re-alert because state was cleared
        ctx3 = _ctx(positions=pos, prices={"BTC": 100}, tick=3)
        it.tick(ctx3)
        assert len(ctx3.alerts) == 1
        assert ctx3.alerts[0].severity == "warning"


class TestMultiplePositions:
    def test_independent_alerts_per_instrument(self):
        it = LiquidationMonitorIterator()
        positions = [
            _long("BTC", 1, 100, 70),    # cushion=30% → safe
            _long("ETH", 10, 50, 49.5),  # cushion=1% → critical
            _short("SOL", 5, 200, 206),  # cushion=3% → warning
        ]
        prices = {"BTC": 100, "ETH": 50, "SOL": 200}
        ctx = _ctx(positions=positions, prices=prices)
        it.tick(ctx)
        # 2 alerts (BTC safe, no alert)
        assert len(ctx.alerts) == 2
        sources = {a.data["instrument"]: a.severity for a in ctx.alerts}
        assert sources["ETH"] == "critical"
        assert sources["SOL"] == "warning"
