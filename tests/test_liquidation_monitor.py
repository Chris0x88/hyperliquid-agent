"""Tests for LiquidationMonitorIterator — margin-burn alerts.

Uses margin_remaining (current_cushion / entry_cushion) so that positions
at entry price are ALWAYS safe regardless of leverage. Only alerts when
you've lost a meaningful fraction of your starting margin.
"""
from decimal import Decimal
from unittest import mock

import pytest

from daemon.context import TickContext
from daemon.iterators.liquidation_monitor import (
    LiquidationMonitorIterator,
    SAFE_THRESHOLD,
    WARN_THRESHOLD,
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
    """_classify takes margin_remaining (fraction of initial cushion left)."""

    def test_safe(self):
        assert _classify(Decimal("1.0"), "safe") == "safe"  # at entry
        assert _classify(Decimal("0.80"), "safe") == "safe"  # lost 20%
        assert _classify(SAFE_THRESHOLD, "safe") == "safe"   # boundary

    def test_warning_band(self):
        assert _classify(Decimal("0.40"), "safe") == "warning"
        assert _classify(WARN_THRESHOLD, "safe") == "warning"

    def test_critical(self):
        assert _classify(Decimal("0.10"), "safe") == "critical"
        assert _classify(Decimal("0"), "safe") == "critical"

    def test_hysteresis_warning_to_safe(self):
        """Need 60% margin remaining to escape warning → safe."""
        assert _classify(Decimal("0.55"), "warning") == "warning"  # 55% not enough
        assert _classify(Decimal("0.61"), "warning") == "safe"     # 61% clears it


class TestAtEntryPriceAlwaysSafe:
    """The core fix: at entry price, margin_remaining=100%, always safe."""

    def test_25x_at_entry_is_safe(self):
        """Silver 25x at entry price must NOT alert."""
        it = LiquidationMonitorIterator()
        # entry=80.50, liq=78.91, mark=80.50 (at entry)
        # entry_cushion = 80.50 - 78.91 = 1.59
        # current_cushion = 80.50 - 78.91 = 1.59
        # margin_remaining = 1.59 / 1.59 = 1.0 (100%) → safe
        ctx = _ctx(
            positions=[_long("SILVER", 1, 80.50, 78.91, lev=25)],
            prices={"SILVER": 80.50},
        )
        it.tick(ctx)
        assert ctx.alerts == []

    def test_37x_at_entry_is_safe(self):
        """BTC 37x at entry price must NOT alert."""
        it = LiquidationMonitorIterator()
        ctx = _ctx(
            positions=[_long("BTC", 1, 74650, 71837, lev=37)],
            prices={"BTC": 74650},
        )
        it.tick(ctx)
        assert ctx.alerts == []

    def test_10x_at_entry_is_safe(self):
        """Oil 10x at entry price must NOT alert."""
        it = LiquidationMonitorIterator()
        ctx = _ctx(
            positions=[_long("CL", 1, 100, 91, lev=10)],
            prices={"CL": 100},
        )
        it.tick(ctx)
        assert ctx.alerts == []

    def test_above_entry_is_safe(self):
        """In profit → margin_remaining > 100% → definitely safe."""
        it = LiquidationMonitorIterator()
        # entry=100, liq=91, mark=105 (in profit)
        # entry_cushion = 100-91 = 9, current = 105-91 = 14
        # margin_remaining = 14/9 = 1.56 → super safe
        ctx = _ctx(
            positions=[_long("CL", 1, 100, 91, lev=10)],
            prices={"CL": 105},
        )
        it.tick(ctx)
        assert ctx.alerts == []


class TestWarningWhenMarginConsumed:
    """Alerts fire when you've lost a significant chunk of your entry margin."""

    def test_lost_60pct_of_margin_is_warning(self):
        it = LiquidationMonitorIterator()
        # entry=100, liq=91, entry_cushion=9
        # For 40% remaining: current_cushion = 9 * 0.40 = 3.6
        # mark = liq + 3.6 = 94.6
        ctx = _ctx(
            positions=[_long("CL", 1, 100, 91, lev=10)],
            prices={"CL": 94.6},
        )
        it.tick(ctx)
        assert len(ctx.alerts) == 1
        assert ctx.alerts[0].severity == "warning"

    def test_lost_80pct_of_margin_is_critical(self):
        it = LiquidationMonitorIterator()
        # entry=100, liq=91, entry_cushion=9
        # For 20% remaining: current_cushion = 9 * 0.20 = 1.8
        # mark = liq + 1.8 = 92.8
        ctx = _ctx(
            positions=[_long("CL", 1, 100, 91, lev=10)],
            prices={"CL": 92.8},
        )
        it.tick(ctx)
        assert len(ctx.alerts) == 1
        assert ctx.alerts[0].severity == "critical"

    def test_alert_shows_margin_remaining(self):
        it = LiquidationMonitorIterator()
        ctx = _ctx(
            positions=[_long("CL", 1, 100, 91, lev=10)],
            prices={"CL": 94.6},
        )
        it.tick(ctx)
        assert len(ctx.alerts) == 1
        assert "margin_remaining_pct" in ctx.alerts[0].data
        assert "Margin left" in ctx.alerts[0].message


class TestShortPosition:
    def test_short_at_entry_safe(self):
        it = LiquidationMonitorIterator()
        # short: entry=100, liq=109, mark=100 (at entry)
        # entry_cushion = 109-100 = 9, current = 109-100 = 9 → 100% → safe
        ctx = _ctx(positions=[_short("BTC", 1, 100, 109)], prices={"BTC": 100})
        it.tick(ctx)
        assert ctx.alerts == []

    def test_short_warning(self):
        it = LiquidationMonitorIterator()
        # short: entry=100, liq=109, mark=105.4
        # entry_cushion = 9, current = 109-105.4 = 3.6 → 40% → warning
        ctx = _ctx(positions=[_short("BTC", 1, 100, 109)], prices={"BTC": 105.4})
        it.tick(ctx)
        assert len(ctx.alerts) == 1
        assert ctx.alerts[0].severity == "warning"
        assert "SHORT" in ctx.alerts[0].message

    def test_short_critical(self):
        it = LiquidationMonitorIterator()
        # short: entry=100, liq=109, mark=107.2
        # current = 109-107.2 = 1.8 → 20% → critical
        ctx = _ctx(positions=[_short("BTC", 1, 100, 109)], prices={"BTC": 107.2})
        it.tick(ctx)
        assert len(ctx.alerts) == 1
        assert ctx.alerts[0].severity == "critical"


class TestAntiSpam:
    def test_warning_fires_once(self):
        it = LiquidationMonitorIterator()
        pos = [_long("CL", 1, 100, 91)]
        prices = {"CL": 94.6}  # 40% remaining → warning
        ctx1 = _ctx(positions=pos, prices=prices, tick=1)
        it.tick(ctx1)
        assert len(ctx1.alerts) == 1
        ctx2 = _ctx(positions=pos, prices=prices, tick=2)
        it.tick(ctx2)
        assert ctx2.alerts == []

    def test_critical_no_repeat_when_not_worsened(self):
        it = LiquidationMonitorIterator()
        pos = [_long("CL", 1, 100, 91)]
        prices = {"CL": 92.8}  # 20% remaining → critical
        ctx1 = _ctx(positions=pos, prices=prices, tick=1)
        it.tick(ctx1)
        assert len(ctx1.alerts) == 1
        with mock.patch("daemon.iterators.liquidation_monitor.time") as mt:
            mt.monotonic.return_value = CRITICAL_REPEAT_SECS + 100
            ctx2 = _ctx(positions=pos, prices=prices, tick=50)
            it.tick(ctx2)
            assert ctx2.alerts == []  # same margin → no repeat

    def test_critical_repeats_when_worsened(self):
        it = LiquidationMonitorIterator()
        pos = [_long("CL", 1, 100, 91)]
        ctx1 = _ctx(positions=pos, prices={"CL": 92.8}, tick=1)  # 20% margin
        it.tick(ctx1)
        assert len(ctx1.alerts) == 1
        first_time = it._last_critical_time["CL"]
        # Worsen: price drops to 91.9 → 10% margin
        with mock.patch("daemon.iterators.liquidation_monitor.time") as mt:
            mt.monotonic.return_value = first_time + CRITICAL_REPEAT_SECS + 1
            ctx2 = _ctx(positions=pos, prices={"CL": 91.9}, tick=50)
            it.tick(ctx2)
            assert len(ctx2.alerts) == 1
            assert ctx2.alerts[0].severity == "critical"

    def test_oscillation_dampening(self):
        it = LiquidationMonitorIterator()
        pos = [_long("CL", 1, 100, 91)]  # entry_cushion = 9
        # Start at warning: mark=94.6, margin=40%
        ctx1 = _ctx(positions=pos, prices={"CL": 94.6}, tick=1)
        it.tick(ctx1)
        assert len(ctx1.alerts) == 1
        assert ctx1.alerts[0].severity == "warning"

        # Price bounces up: mark=96, margin=(96-91)/9=55.6% — above 50% safe
        # but below 60% hysteresis → stays warning, no alert
        ctx2 = _ctx(positions=pos, prices={"CL": 96}, tick=2)
        it.tick(ctx2)
        assert ctx2.alerts == []  # no recovery (hysteresis)

        # Price drops back → still warning → no new alert
        ctx3 = _ctx(positions=pos, prices={"CL": 94.6}, tick=3)
        it.tick(ctx3)
        assert ctx3.alerts == []


class TestRecovery:
    def test_recovery_from_warning(self):
        it = LiquidationMonitorIterator()
        pos = [_long("CL", 1, 100, 91)]
        # Warning: mark=94.6, margin=40%
        ctx1 = _ctx(positions=pos, prices={"CL": 94.6}, tick=1)
        it.tick(ctx1)
        assert ctx1.alerts[0].severity == "warning"
        # Recovery: mark=98, margin=(98-91)/9=77.8% → past 60% hysteresis → safe
        ctx2 = _ctx(positions=pos, prices={"CL": 98}, tick=2)
        it.tick(ctx2)
        assert len(ctx2.alerts) == 1
        assert ctx2.alerts[0].severity == "info"
        assert "RECOVERED" in ctx2.alerts[0].message

    def test_recovery_from_critical(self):
        it = LiquidationMonitorIterator()
        pos = [_long("CL", 1, 100, 91)]
        ctx1 = _ctx(positions=pos, prices={"CL": 92.8}, tick=1)
        it.tick(ctx1)
        assert ctx1.alerts[0].severity == "critical"
        # Big rally back above entry
        ctx2 = _ctx(positions=pos, prices={"CL": 102}, tick=2)
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
            positions=[_long("CL", 1, 100, 91)],
            prices={"CL": 94.6},
            tick=1,
        )
        it.tick(ctx1)
        assert "CL" in it._last_tier
        ctx2 = _ctx(positions=[], prices={"CL": 100}, tick=2)
        it.tick(ctx2)
        assert "CL" not in it._last_tier

    def test_reopened_position_alerts_again(self):
        it = LiquidationMonitorIterator()
        pos = [_long("CL", 1, 100, 91)]
        ctx1 = _ctx(positions=pos, prices={"CL": 94.6}, tick=1)
        it.tick(ctx1)
        assert len(ctx1.alerts) == 1
        ctx2 = _ctx(positions=[], prices={"CL": 100}, tick=2)
        it.tick(ctx2)
        ctx3 = _ctx(positions=pos, prices={"CL": 94.6}, tick=3)
        it.tick(ctx3)
        assert len(ctx3.alerts) == 1
        assert ctx3.alerts[0].severity == "warning"


class TestMultiplePositions:
    def test_independent_alerts(self):
        it = LiquidationMonitorIterator()
        positions = [
            _long("BTC", 1, 100, 91, lev=10),    # mark=100, at entry → safe
            _long("ETH", 10, 50, 46, lev=10),     # mark=47, margin=(47-46)/(50-46)=25% → warning
            _short("SOL", 5, 200, 218, lev=10),   # mark=214.4, margin=(218-214.4)/(218-200)=20% → critical
        ]
        prices = {"BTC": 100, "ETH": 47, "SOL": 214.4}
        ctx = _ctx(positions=positions, prices=prices)
        it.tick(ctx)
        assert len(ctx.alerts) == 2
        sources = {a.data["instrument"]: a.severity for a in ctx.alerts}
        assert sources["ETH"] == "warning"
        assert sources["SOL"] == "critical"
