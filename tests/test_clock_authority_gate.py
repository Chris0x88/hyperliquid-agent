"""Tests for the H3 defense-in-depth authority gate in Clock._execute_orders.

Closes the LATENT-REBALANCE gap from the 2026-04-07 verification ledger:
even if some upstream iterator queues an OrderIntent for a non-delegated
asset (e.g. a future iterator that doesn't check authority), Clock will
refuse to forward it to the adapter and will surface a CRITICAL alert
naming the originating strategy.

Production runs in WATCH tier where order_queue is always empty, so this
is a tier-promotion gate, not an active production fix.
"""
from __future__ import annotations

from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest

from daemon.clock import Clock
from daemon.config import DaemonConfig
from daemon.context import OrderIntent, TickContext
from daemon.roster import Roster
from daemon.state import StateStore
from exchange.risk_manager import RiskGate


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_clock(tmp_path) -> tuple[Clock, MagicMock]:
    """Construct a real Clock with isolated tmp paths and a mock adapter."""
    config = DaemonConfig(tier="rebalance", tick_interval=1.0, mock=False)
    store = StateStore(data_dir=str(tmp_path / "daemon"))
    roster = Roster(path=str(tmp_path / "roster.json"))
    adapter = MagicMock()
    # adapter.place_order returns nothing meaningful; we just observe calls
    clock = Clock(config=config, roster=roster, store=store, adapter=adapter)
    return clock, adapter


def _intent(
    instrument: str,
    action: str = "buy",
    size: float = 1.0,
    price: float = 100.0,
    reduce_only: bool = False,
    strategy: str = "execution_engine",
) -> OrderIntent:
    return OrderIntent(
        strategy_name=strategy,
        instrument=instrument,
        action=action,
        size=Decimal(str(size)),
        price=Decimal(str(price)),
        reduce_only=reduce_only,
    )


def _ctx_with_orders(intents: list[OrderIntent]) -> TickContext:
    c = TickContext()
    c.order_queue = list(intents)
    c.risk_gate = RiskGate.OPEN
    return c


# ---------------------------------------------------------------------------
# H3 Authority Gate Tests
# ---------------------------------------------------------------------------


class TestClockAuthorityGate:
    def test_agent_managed_order_is_submitted(self, tmp_path):
        """An OrderIntent for an agent-delegated asset gets forwarded to the adapter."""
        clock, adapter = _make_clock(tmp_path)
        ctx = _ctx_with_orders([_intent("BTC", action="buy", size=1.0)])

        with patch("daemon.clock.is_agent_managed", return_value=True):
            clock._execute_orders(ctx)

        # Adapter received the order
        assert adapter.place_order.called
        # Order queue is now drained
        assert ctx.order_queue == []
        # No critical authority alerts
        critical_alerts = [a for a in ctx.alerts if a.severity == "critical"]
        assert critical_alerts == []

    def test_non_agent_order_is_dropped_with_critical_alert(self, tmp_path):
        """An OrderIntent for a non-delegated asset is NOT submitted and raises CRITICAL."""
        clock, adapter = _make_clock(tmp_path)
        ctx = _ctx_with_orders([_intent("GOLD", action="buy", size=0.5)])

        with patch("daemon.clock.is_agent_managed", return_value=False):
            clock._execute_orders(ctx)

        # Adapter was NOT called
        assert not adapter.place_order.called
        assert not adapter.cancel_all.called
        # Order queue is drained
        assert ctx.order_queue == []
        # CRITICAL alert was added
        critical_alerts = [
            a for a in ctx.alerts
            if a.severity == "critical" and a.source == "clock"
        ]
        assert len(critical_alerts) == 1
        assert "AUTHORITY GAP" in critical_alerts[0].message
        assert "GOLD" in critical_alerts[0].message
        # Alert data carries the originating strategy
        assert critical_alerts[0].data["instrument"] == "GOLD"
        assert critical_alerts[0].data["strategy"] == "execution_engine"

    def test_mixed_orders_only_agent_submitted(self, tmp_path):
        """When the queue has multiple orders, only agent-managed ones get through."""
        clock, adapter = _make_clock(tmp_path)
        ctx = _ctx_with_orders([
            _intent("BTC", action="buy", size=1.0),
            _intent("GOLD", action="buy", size=0.5),
            _intent("xyz:BRENTOIL", action="sell", size=2.0),
        ])

        def fake_is_agent_managed(asset: str) -> bool:
            return asset in ("BTC", "xyz:BRENTOIL")

        with patch(
            "daemon.clock.is_agent_managed",
            side_effect=fake_is_agent_managed,
        ):
            clock._execute_orders(ctx)

        # 2 orders submitted (BTC and BRENTOIL)
        assert adapter.place_order.call_count == 2
        # 1 critical alert (GOLD)
        critical_alerts = [
            a for a in ctx.alerts
            if a.severity == "critical" and a.source == "clock"
        ]
        assert len(critical_alerts) == 1
        assert "GOLD" in critical_alerts[0].message
        # Queue drained
        assert ctx.order_queue == []

    def test_authority_gate_runs_after_risk_gate_check(self, tmp_path):
        """If risk_gate is CLOSED, ALL orders are dropped before authority check fires."""
        clock, adapter = _make_clock(tmp_path)
        ctx = _ctx_with_orders([_intent("BTC", action="buy", size=1.0)])
        ctx.risk_gate = RiskGate.CLOSED

        with patch("daemon.clock.is_agent_managed", return_value=False) as mock_auth:
            clock._execute_orders(ctx)

        # Authority check was NOT called — risk gate caught it first
        assert not mock_auth.called
        # No place_order, no critical authority alert
        assert not adapter.place_order.called
        critical_alerts = [
            a for a in ctx.alerts
            if a.severity == "critical" and a.source == "clock"
        ]
        assert critical_alerts == []
        # Queue is drained
        assert ctx.order_queue == []

    def test_cooldown_skips_non_reduce_only_before_authority_check(self, tmp_path):
        """COOLDOWN drops non-reduce-only orders. Authority gate runs after."""
        clock, adapter = _make_clock(tmp_path)
        ctx = _ctx_with_orders([
            _intent("BTC", action="buy", size=1.0, reduce_only=False),
            _intent("BTC", action="sell", size=1.0, reduce_only=True),
        ])
        ctx.risk_gate = RiskGate.COOLDOWN

        with patch("daemon.clock.is_agent_managed", return_value=True):
            clock._execute_orders(ctx)

        # The reduce_only sell got through; the non-reduce buy was dropped by COOLDOWN
        assert adapter.place_order.call_count == 1
        # Verify the surviving call was the reduce_only one
        call_args = adapter.place_order.call_args
        assert call_args is not None
        assert call_args.kwargs.get("reduce_only") is True

    def test_noop_action_is_skipped_without_auth_check(self, tmp_path):
        """noop intents are filtered out before any check."""
        clock, adapter = _make_clock(tmp_path)
        ctx = _ctx_with_orders([_intent("BTC", action="noop", size=0.0)])

        with patch("daemon.clock.is_agent_managed", return_value=False) as mock_auth:
            clock._execute_orders(ctx)

        # Authority check was not invoked for the noop
        assert not mock_auth.called
        assert not adapter.place_order.called
        assert ctx.order_queue == []

    def test_empty_order_queue_is_no_op(self, tmp_path):
        """Empty queue means early return — no checks, no alerts."""
        clock, adapter = _make_clock(tmp_path)
        ctx = _ctx_with_orders([])

        with patch("daemon.clock.is_agent_managed", return_value=False) as mock_auth:
            clock._execute_orders(ctx)

        assert not mock_auth.called
        assert not adapter.place_order.called
        assert ctx.alerts == []
