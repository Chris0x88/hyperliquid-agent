"""Tests for LiquidationMonitorIterator — leverage-aware cushion alerts.

Uses the "turns" metric (cushion% × leverage) to normalize risk across
leverage levels. See iterator docstring for tier boundaries and anti-spam rules.
"""
from decimal import Decimal
from unittest import mock

import pytest

from daemon.context import TickContext
from daemon.iterators.liquidation_monitor import (
    LiquidationMonitorIterator,
    SAFE_TURNS,
    WARN_TURNS,
    CRITICAL_REPEAT_SECS,
    CRITICAL_WORSENED_DELTA,
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
    """_classify now takes turns (cushion × leverage) and prev_tier."""

    def test_safe(self):
        assert _classify(Decimal("1.5"), "safe") == "safe"
        assert _classify(SAFE_TURNS, "safe") == "safe"

    def test_warning_band(self):
        assert _classify(Decimal("0.7"), "safe") == "warning"
        assert _classify(WARN_TURNS, "safe") == "warning"

    def test_critical(self):
        assert _classify(Decimal("0.3"), "safe") == "critical"
        assert _classify(Decimal("0"), "safe") == "critical"

    def test_hysteresis_warning_to_safe(self):
        """Need 20% above safe threshold to escape warning → safe."""
        # At exactly SAFE_TURNS, stay in warning (hysteresis)
        assert _classify(SAFE_TURNS, "warning") == "warning"
        # At SAFE_TURNS * 1.19, still warning
        assert _classify(SAFE_TURNS * Decimal("1.19"), "warning") == "warning"
        # At SAFE_TURNS * 1.2, transitions to safe
        assert _classify(SAFE_TURNS * Decimal("1.21"), "warning") == "safe"


class TestLeverageAdjustment:
    """Core value proposition: same % cushion, different leverage = different tier."""

    def test_high_leverage_more_lenient(self):
        """At 37x, 3% cushion = 1.11 turns → safe. At 10x, 3% = 0.30 → critical."""
        it = LiquidationMonitorIterator()

        # 37x leverage, 3% cushion → turns = 1.11 → safe (no alert)
        ctx1 = _ctx(
            positions=[_long("BTC", 1, 100, 97, lev=37)],
            prices={"BTC": 100},
        )
        it.tick(ctx1)
        assert ctx1.alerts == []  # safe at high leverage

        # 10x leverage, 3% cushion → turns = 0.30 → critical
        it2 = LiquidationMonitorIterator()
        ctx2 = _ctx(
            positions=[_long("OIL", 1, 100, 97, lev=10)],
            prices={"OIL": 100},
        )
        it2.tick(ctx2)
        assert len(ctx2.alerts) == 1
        assert ctx2.alerts[0].severity == "critical"

    def test_warning_zone(self):
        """10x, 6% cushion = 0.60 turns → warning."""
        it = LiquidationMonitorIterator()
        # cushion = (100-94)/100 = 6%, turns = 0.6
        ctx = _ctx(
            positions=[_long("OIL", 1, 100, 94, lev=10)],
            prices={"OIL": 100},
        )
        it.tick(ctx)
        assert len(ctx.alerts) == 1
        assert ctx.alerts[0].severity == "warning"
        assert "turns" in ctx.alerts[0].message

    def test_alert_includes_turns_in_message(self):
        """Alert message should show turns value for operator awareness."""
        it = LiquidationMonitorIterator()
        ctx = _ctx(
            positions=[_long("BTC", 1, 100, 99, lev=10)],
            prices={"BTC": 100},
        )
        it.tick(ctx)
        assert len(ctx.alerts) == 1
        assert "turns" in ctx.alerts[0].message.lower()
        assert "turns" in ctx.alerts[0].data


class TestLongPosition:
    def test_safe_no_alert(self):
        it = LiquidationMonitorIterator()
        # mark=100, liq=70, cushion=30%, 10x → turns=3.0 → safe
        ctx = _ctx(positions=[_long("BTC", 1, 100, 70)], prices={"BTC": 100})
        it.tick(ctx)
        assert ctx.alerts == []

    def test_warning_alert_on_transition(self):
        it = LiquidationMonitorIterator()
        # mark=100, liq=94, cushion=6%, 10x → turns=0.6 → warning
        ctx = _ctx(positions=[_long("BTC", 1, 100, 94)], prices={"BTC": 100})
        it.tick(ctx)
        assert len(ctx.alerts) == 1
        a = ctx.alerts[0]
        assert a.severity == "warning"
        assert a.source == "liquidation_monitor"
        assert "BTC" in a.message
        assert "LONG" in a.message
        assert a.data["tier"] == "warning"

    def test_critical_alert_on_transition(self):
        it = LiquidationMonitorIterator()
        # mark=100, liq=99, cushion=1%, 10x → turns=0.1 → critical
        ctx = _ctx(positions=[_long("BTC", 1, 100, 99)], prices={"BTC": 100})
        it.tick(ctx)
        assert len(ctx.alerts) == 1
        a = ctx.alerts[0]
        assert a.severity == "critical"
        assert "CRITICAL" in a.message
        assert a.data["tier"] == "critical"


class TestAntiSpam:
    def test_no_repeat_alert_within_warning_tier(self):
        """Warning fires exactly once — never repeats."""
        it = LiquidationMonitorIterator()
        positions = [_long("BTC", 1, 100, 94)]  # turns=0.6 → warning
        prices = {"BTC": 100}
        ctx1 = _ctx(positions=positions, prices=prices, tick=1)
        it.tick(ctx1)
        assert len(ctx1.alerts) == 1
        # Second tick same tier → no alert
        ctx2 = _ctx(positions=positions, prices=prices, tick=2)
        it.tick(ctx2)
        assert ctx2.alerts == []

    def test_critical_no_repeat_when_not_worsened(self):
        """Critical doesn't repeat if cushion hasn't gotten worse."""
        it = LiquidationMonitorIterator()
        positions = [_long("BTC", 1, 100, 99)]  # turns=0.1 → critical
        prices = {"BTC": 100}
        # First tick → alert
        ctx1 = _ctx(positions=positions, prices=prices, tick=1)
        it.tick(ctx1)
        assert len(ctx1.alerts) == 1
        # Advance time past CRITICAL_REPEAT_SECS but cushion unchanged
        with mock.patch("daemon.iterators.liquidation_monitor.time") as mock_time:
            mock_time.monotonic.return_value = CRITICAL_REPEAT_SECS + 100
            ctx2 = _ctx(positions=positions, prices=prices, tick=50)
            it.tick(ctx2)
            assert ctx2.alerts == []  # not worsened → no repeat

    def test_critical_repeats_when_worsened_and_time_elapsed(self):
        """Critical repeats only when BOTH conditions met: time elapsed AND cushion worse."""
        it = LiquidationMonitorIterator()
        # Initial: mark=100, liq=99, cushion=1%, turns=0.1 → critical
        ctx1 = _ctx(
            positions=[_long("BTC", 1, 100, 99)],
            prices={"BTC": 100},
            tick=1,
        )
        it.tick(ctx1)
        assert len(ctx1.alerts) == 1
        # Record the time of the first alert
        first_alert_time = it._last_critical_time["BTC"]

        # Advance time and worsen cushion: mark=99.5, cushion=0.5%
        with mock.patch("daemon.iterators.liquidation_monitor.time") as mock_time:
            mock_time.monotonic.return_value = first_alert_time + CRITICAL_REPEAT_SECS + 1
            ctx2 = _ctx(
                positions=[_long("BTC", 1, 100, 99)],
                prices={"BTC": 99.5},
                tick=50,
            )
            it.tick(ctx2)
            assert len(ctx2.alerts) == 1  # worsened + time elapsed → repeat
            assert ctx2.alerts[0].severity == "critical"

    def test_oscillation_dampening(self):
        """Price bouncing around warning/safe boundary doesn't spam."""
        it = LiquidationMonitorIterator()
        # Start at warning: cushion=6%, 10x → turns=0.6
        pos = [_long("BTC", 1, 100, 94)]
        ctx1 = _ctx(positions=pos, prices={"BTC": 100}, tick=1)
        it.tick(ctx1)
        assert len(ctx1.alerts) == 1  # warning
        assert ctx1.alerts[0].severity == "warning"

        # Price bounces up slightly: cushion=10.9%, turns=1.09 — above SAFE_TURNS
        # but below SAFE_TURNS * 1.2 hysteresis → stays warning, no alert
        ctx2 = _ctx(positions=pos, prices={"BTC": 105.5}, tick=2)
        it.tick(ctx2)
        assert ctx2.alerts == []  # no recovery alert (hysteresis)

        # Price bounces back down → still warning → no new alert
        ctx3 = _ctx(positions=pos, prices={"BTC": 100}, tick=3)
        it.tick(ctx3)
        assert ctx3.alerts == []  # no new warning (already in warning)


class TestShortPosition:
    def test_safe(self):
        it = LiquidationMonitorIterator()
        # short: mark=100, liq=130, cushion=30%, 10x → turns=3.0 → safe
        ctx = _ctx(positions=[_short("BTC", 1, 100, 130)], prices={"BTC": 100})
        it.tick(ctx)
        assert ctx.alerts == []

    def test_warning(self):
        it = LiquidationMonitorIterator()
        # short: mark=100, liq=106, cushion=6%, 10x → turns=0.6 → warning
        ctx = _ctx(positions=[_short("BTC", 1, 100, 106)], prices={"BTC": 100})
        it.tick(ctx)
        assert len(ctx.alerts) == 1
        assert ctx.alerts[0].severity == "warning"
        assert "SHORT" in ctx.alerts[0].message

    def test_critical(self):
        it = LiquidationMonitorIterator()
        # short: mark=100, liq=101, cushion=1%, 10x → turns=0.1 → critical
        ctx = _ctx(positions=[_short("BTC", 1, 100, 101)], prices={"BTC": 100})
        it.tick(ctx)
        assert len(ctx.alerts) == 1
        assert ctx.alerts[0].severity == "critical"


class TestRecovery:
    def test_recovery_alert_warning_to_safe(self):
        it = LiquidationMonitorIterator()
        pos = [_long("BTC", 1, 100, 94)]  # 10x, cushion=6% → turns=0.6 → warning
        ctx1 = _ctx(positions=pos, prices={"BTC": 100}, tick=1)
        it.tick(ctx1)
        assert ctx1.alerts[0].severity == "warning"
        # Price rallies hard: cushion=(125-94)/125=24.8%, turns=2.48 → past hysteresis → safe
        ctx2 = _ctx(positions=pos, prices={"BTC": 125}, tick=2)
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
        # Big rally: cushion=(150-99)/150=34%, turns=3.4 → safe
        ctx2 = _ctx(positions=pos, prices={"BTC": 150}, tick=2)
        it.tick(ctx2)
        assert ctx2.alerts[0].severity == "info"
        assert "RECOVERED" in ctx2.alerts[0].message


class TestMissingData:
    def test_missing_liq_price(self):
        it = LiquidationMonitorIterator()
        pos = _long("BTC", 1, 100, 0)
        ctx = _ctx(positions=[pos], prices={"BTC": 100})
        it.tick(ctx)
        assert ctx.alerts == []

    def test_missing_mark_price(self):
        it = LiquidationMonitorIterator()
        ctx = _ctx(positions=[_long("BTC", 1, 100, 95)], prices={})
        it.tick(ctx)
        assert ctx.alerts == []

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
        ctx1 = _ctx(
            positions=[_long("BTC", 1, 100, 94)],
            prices={"BTC": 100},
            tick=1,
        )
        it.tick(ctx1)
        assert "BTC" in it._last_tier
        ctx2 = _ctx(positions=[], prices={"BTC": 100}, tick=2)
        it.tick(ctx2)
        assert "BTC" not in it._last_tier

    def test_reopened_position_alerts_again(self):
        it = LiquidationMonitorIterator()
        pos = [_long("BTC", 1, 100, 94)]  # turns=0.6 → warning
        ctx1 = _ctx(positions=pos, prices={"BTC": 100}, tick=1)
        it.tick(ctx1)
        assert len(ctx1.alerts) == 1
        ctx2 = _ctx(positions=[], prices={"BTC": 100}, tick=2)
        it.tick(ctx2)
        ctx3 = _ctx(positions=pos, prices={"BTC": 100}, tick=3)
        it.tick(ctx3)
        assert len(ctx3.alerts) == 1
        assert ctx3.alerts[0].severity == "warning"


class TestMultiplePositions:
    def test_independent_alerts_per_instrument(self):
        it = LiquidationMonitorIterator()
        positions = [
            _long("BTC", 1, 100, 70, lev=10),    # cushion=30%, turns=3.0 → safe
            _long("ETH", 10, 50, 49.5, lev=10),   # cushion=1%, turns=0.1 → critical
            _short("SOL", 5, 200, 212, lev=10),    # cushion=6%, turns=0.6 → warning
        ]
        prices = {"BTC": 100, "ETH": 50, "SOL": 200}
        ctx = _ctx(positions=positions, prices=prices)
        it.tick(ctx)
        assert len(ctx.alerts) == 2
        sources = {a.data["instrument"]: a.severity for a in ctx.alerts}
        assert sources["ETH"] == "critical"
        assert sources["SOL"] == "warning"
