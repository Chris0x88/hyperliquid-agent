"""Unit tests for daemon.iterators.portfolio_risk_monitor.

Focuses on the alert state-machine and SL resolution logic. The iterator is
alert-only; we verify it never closes positions and never raises the gate
when disabled.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import List

import pytest

from daemon.context import Alert, TickContext
from daemon.iterators.portfolio_risk_monitor import (
    PortfolioRiskConfig,
    PortfolioRiskMonitorIterator,
)
from exchange.risk_manager import RiskGate


# ── Fakes ─────────────────────────────────────────────────────────────────

@dataclass
class _FakePos:
    instrument: str
    net_qty: Decimal
    avg_entry_price: Decimal
    liquidation_price: Decimal


class _FakeAdapter:
    """Returns whatever orders we hand it."""

    def __init__(self, orders: List[dict]):
        self._orders = orders

    def get_open_orders(self):
        return list(self._orders)


def _ctx(equity: float, positions: List[_FakePos]) -> TickContext:
    ctx = TickContext()
    ctx.total_equity = equity
    ctx.positions = positions  # type: ignore[assignment]
    return ctx


def _force_tick(it: PortfolioRiskMonitorIterator) -> None:
    """Bypass the throttle so each test tick actually runs."""
    it._last_tick = 0.0


# ── Tests ─────────────────────────────────────────────────────────────────

def test_disabled_does_nothing():
    it = PortfolioRiskMonitorIterator(
        adapter=None,
        config=PortfolioRiskConfig(enabled=False),
    )
    ctx = _ctx(1000.0, [_FakePos("BTC", Decimal("1"), Decimal("100"), Decimal("80"))])
    _force_tick(it)
    it.tick(ctx)
    assert ctx.alerts == []
    assert ctx.risk_gate == RiskGate.OPEN


def test_safe_below_warn_threshold():
    """1% open risk on $1000 equity → no alert."""
    cfg = PortfolioRiskConfig(enabled=True, warn_pct=Decimal("0.08"), cap_pct=Decimal("0.10"))
    # entry 100, SL 99 (long), size 10 → risk = $10 = 1% of $1000
    sl_order = {"coin": "BTC", "orderType": {"trigger": {"triggerPx": "99", "tpsl": "sl"}}}
    it = PortfolioRiskMonitorIterator(adapter=_FakeAdapter([sl_order]), config=cfg)
    ctx = _ctx(1000.0, [_FakePos("BTC", Decimal("10"), Decimal("100"), Decimal("80"))])
    _force_tick(it)
    it.tick(ctx)
    assert ctx.alerts == []
    assert ctx.risk_gate == RiskGate.OPEN


def test_warning_at_warn_threshold():
    """8% risk → one warning alert."""
    cfg = PortfolioRiskConfig(enabled=True, warn_pct=Decimal("0.08"), cap_pct=Decimal("0.10"))
    # entry 100, SL 92 (long), size 10 → risk = $80 = 8% of $1000
    sl_order = {"coin": "BTC", "orderType": {"trigger": {"triggerPx": "92", "tpsl": "sl"}}}
    it = PortfolioRiskMonitorIterator(adapter=_FakeAdapter([sl_order]), config=cfg)
    ctx = _ctx(1000.0, [_FakePos("BTC", Decimal("10"), Decimal("100"), Decimal("80"))])
    _force_tick(it)
    it.tick(ctx)
    assert len(ctx.alerts) == 1
    assert ctx.alerts[0].severity == "warning"
    assert "Portfolio risk WARNING" in ctx.alerts[0].message
    # Warning never throttles new entries.
    assert ctx.risk_gate == RiskGate.OPEN


def test_critical_at_cap_throttles_entries_only():
    """11% risk → critical alert + COOLDOWN gate (entry throttle), NEVER closes."""
    cfg = PortfolioRiskConfig(enabled=True, warn_pct=Decimal("0.08"), cap_pct=Decimal("0.10"))
    # entry 100, SL 89 (long), size 10 → risk = $110 = 11% of $1000
    sl_order = {"coin": "BTC", "orderType": {"trigger": {"triggerPx": "89", "tpsl": "sl"}}}
    it = PortfolioRiskMonitorIterator(adapter=_FakeAdapter([sl_order]), config=cfg)
    pos = _FakePos("BTC", Decimal("10"), Decimal("100"), Decimal("80"))
    ctx = _ctx(1000.0, [pos])
    _force_tick(it)
    it.tick(ctx)
    assert len(ctx.alerts) == 1
    assert ctx.alerts[0].severity == "critical"
    assert "CAP REACHED" in ctx.alerts[0].message
    assert ctx.risk_gate == RiskGate.COOLDOWN
    # Critical NEVER closes positions — invariant per Chris's rule.
    assert ctx.positions == [pos]
    assert ctx.order_queue == []


def test_state_change_dedup_does_not_re_alert():
    """Same state across ticks → no duplicate alert."""
    cfg = PortfolioRiskConfig(enabled=True, warn_pct=Decimal("0.08"), cap_pct=Decimal("0.10"))
    sl_order = {"coin": "BTC", "orderType": {"trigger": {"triggerPx": "92", "tpsl": "sl"}}}
    it = PortfolioRiskMonitorIterator(adapter=_FakeAdapter([sl_order]), config=cfg)
    ctx = _ctx(1000.0, [_FakePos("BTC", Decimal("10"), Decimal("100"), Decimal("80"))])
    _force_tick(it)
    it.tick(ctx)
    _force_tick(it)
    it.tick(ctx)
    _force_tick(it)
    it.tick(ctx)
    assert len(ctx.alerts) == 1  # one warning, then deduped


def test_recovery_emits_one_info_alert():
    """warn → safe transition emits a single info alert."""
    cfg = PortfolioRiskConfig(enabled=True, warn_pct=Decimal("0.08"), cap_pct=Decimal("0.10"))
    # First tick: warning state
    sl_order = {"coin": "BTC", "orderType": {"trigger": {"triggerPx": "92", "tpsl": "sl"}}}
    it = PortfolioRiskMonitorIterator(adapter=_FakeAdapter([sl_order]), config=cfg)
    ctx = _ctx(1000.0, [_FakePos("BTC", Decimal("10"), Decimal("100"), Decimal("80"))])
    _force_tick(it)
    it.tick(ctx)
    assert ctx.alerts[-1].severity == "warning"
    # Move SL closer to entry → risk drops
    it._trigger_cache = {}  # force refetch on next tick
    it._adapter = _FakeAdapter([{"coin": "BTC", "orderType": {"trigger": {"triggerPx": "99", "tpsl": "sl"}}}])
    _force_tick(it)
    it.tick(ctx)
    assert ctx.alerts[-1].severity == "info"
    assert "recovered" in ctx.alerts[-1].message


def test_liquidation_fallback_when_no_sl():
    """No SL order → uses liquidation as worst-case SL."""
    cfg = PortfolioRiskConfig(enabled=True, warn_pct=Decimal("0.08"), cap_pct=Decimal("0.10"))
    # entry 100, liq 80, size 10 → fallback risk = $200 = 20% of $1000 → critical
    it = PortfolioRiskMonitorIterator(adapter=_FakeAdapter([]), config=cfg)
    ctx = _ctx(1000.0, [_FakePos("BTC", Decimal("10"), Decimal("100"), Decimal("80"))])
    _force_tick(it)
    it.tick(ctx)
    assert ctx.alerts[0].severity == "critical"
    assert "liquidation_fallback" in ctx.alerts[0].message


def test_xyz_prefix_match_finds_sl():
    """xyz: prefix mismatch is the recurring bug — SL on 'xyz:SILVER' must match position 'xyz:SILVER'."""
    cfg = PortfolioRiskConfig(enabled=True, warn_pct=Decimal("0.08"), cap_pct=Decimal("0.10"))
    # SL order on 'xyz:SILVER', position on 'xyz:SILVER' — should match cleanly
    sl_order = {"coin": "xyz:SILVER", "orderType": {"trigger": {"triggerPx": "92", "tpsl": "sl"}}}
    it = PortfolioRiskMonitorIterator(adapter=_FakeAdapter([sl_order]), config=cfg)
    ctx = _ctx(1000.0, [_FakePos("xyz:SILVER", Decimal("10"), Decimal("100"), Decimal("80"))])
    _force_tick(it)
    it.tick(ctx)
    # 8% → warning (matched the SL, not the liq fallback)
    assert ctx.alerts[0].severity == "warning"
    assert "liquidation_fallback" not in ctx.alerts[0].message


def test_zero_equity_does_not_divide():
    """Defensive: equity not yet populated → no alert, no crash."""
    cfg = PortfolioRiskConfig(enabled=True)
    it = PortfolioRiskMonitorIterator(adapter=_FakeAdapter([]), config=cfg)
    ctx = _ctx(0.0, [_FakePos("BTC", Decimal("10"), Decimal("100"), Decimal("80"))])
    _force_tick(it)
    it.tick(ctx)
    assert ctx.alerts == []
