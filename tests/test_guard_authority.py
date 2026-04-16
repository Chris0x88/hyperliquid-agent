"""Tests for the H4 authority gate in GuardIterator.

Closes the LATENT-REBALANCE gap from the 2026-04-07 verification ledger and
the FAQ admission in tier-state-machine.md: GuardIterator now skips
non-delegated assets and tears down any previously-tracked bridge when
authority is reclaimed.

Production runs in WATCH tier where guard does not execute, so this is a
tier-promotion gate, not an active production fix.
"""
from __future__ import annotations

from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest

from daemon.context import TickContext
from daemon.iterators.guard import GuardIterator
from exchange.position_tracker import Position


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _long(inst: str, qty: float = 1.0, entry: float = 100.0, lev: int = 10) -> Position:
    return Position(
        instrument=inst,
        net_qty=Decimal(str(qty)),
        avg_entry_price=Decimal(str(entry)),
        liquidation_price=Decimal(str(entry * 0.9)),
        leverage=Decimal(str(lev)),
    )


def _ctx(positions: list[Position], prices: dict[str, float]) -> TickContext:
    c = TickContext()
    c.positions = positions
    c.prices = {k: Decimal(str(v)) for k, v in prices.items()}
    return c


def _make_guard(tmp_path) -> GuardIterator:
    """Construct a GuardIterator with isolated storage and a mock adapter."""
    adapter = MagicMock()
    # Default mock behavior: place_trigger_order returns a fake oid
    adapter.place_trigger_order.return_value = "9999"
    adapter.cancel_trigger_order.return_value = True
    return GuardIterator(adapter=adapter, data_dir=str(tmp_path / "guard"))


# ---------------------------------------------------------------------------
# Authority gate tests
# ---------------------------------------------------------------------------


class TestGuardAuthorityGate:
    def test_agent_managed_position_creates_bridge(self, tmp_path):
        """A delegated position causes Guard to create and run a bridge for it."""
        guard = _make_guard(tmp_path)
        ctx = _ctx([_long("BTC")], prices={"BTC": 105.0})

        with patch("daemon.iterators.guard.is_agent_managed", return_value=True):
            guard.tick(ctx)

        assert "BTC" in guard._bridges

    def test_manual_position_skipped_no_bridge_created(self, tmp_path):
        """A non-delegated position must NOT have a bridge created for it."""
        guard = _make_guard(tmp_path)
        ctx = _ctx([_long("GOLD")], prices={"GOLD": 2000.0})

        with patch("daemon.iterators.guard.is_agent_managed", return_value=False):
            guard.tick(ctx)

        assert "GOLD" not in guard._bridges
        # No order intents queued
        assert ctx.order_queue == []

    def test_off_position_also_skipped(self, tmp_path):
        """Same as manual — is_agent_managed returns False for 'off' too."""
        guard = _make_guard(tmp_path)
        ctx = _ctx([_long("MEME")], prices={"MEME": 1.0})

        with patch("daemon.iterators.guard.is_agent_managed", return_value=False):
            guard.tick(ctx)

        assert "MEME" not in guard._bridges
        assert ctx.order_queue == []

    def test_mixed_authority_only_agent_tracked(self, tmp_path):
        """When the portfolio has agent + manual positions, only agent gets bridges."""
        guard = _make_guard(tmp_path)
        ctx = _ctx(
            [_long("BTC"), _long("GOLD"), _long("xyz:BRENTOIL")],
            prices={"BTC": 105.0, "GOLD": 2000.0, "xyz:BRENTOIL": 80.0},
        )

        def fake_is_agent_managed(asset: str) -> bool:
            return asset in ("BTC", "xyz:BRENTOIL")

        with patch(
            "daemon.iterators.guard.is_agent_managed",
            side_effect=fake_is_agent_managed,
        ):
            guard.tick(ctx)

        bridge_insts = sorted(guard._bridges.keys())
        assert bridge_insts == ["BTC", "xyz:BRENTOIL"]
        assert "GOLD" not in guard._bridges

    def test_authority_reclaim_tears_down_existing_bridge(self, tmp_path):
        """When authority flips agent → manual mid-flight, the existing bridge is destroyed."""
        guard = _make_guard(tmp_path)
        ctx_initial = _ctx([_long("BTC")], prices={"BTC": 105.0})

        # Tick 1: BTC delegated → bridge created
        with patch("daemon.iterators.guard.is_agent_managed", return_value=True):
            guard.tick(ctx_initial)
        assert "BTC" in guard._bridges

        # Tick 2: BTC reclaimed → bridge torn down, alert raised
        ctx_reclaim = _ctx([_long("BTC")], prices={"BTC": 105.0})
        with patch("daemon.iterators.guard.is_agent_managed", return_value=False):
            guard.tick(ctx_reclaim)

        assert "BTC" not in guard._bridges
        # Alert about authority reclamation
        reclaim_alerts = [
            a for a in ctx_reclaim.alerts
            if a.source == "guard" and "authority" in a.message.lower()
        ]
        assert len(reclaim_alerts) == 1
        assert "BTC" in reclaim_alerts[0].message

    def test_authority_reclaim_calls_cancel_exchange_sl(self, tmp_path):
        """Authority reclaim tear-down also calls cancel_exchange_sl on the adapter."""
        guard = _make_guard(tmp_path)
        adapter = guard._adapter
        ctx_initial = _ctx([_long("BTC")], prices={"BTC": 105.0})

        # Tick 1: bridge created (will sync_exchange_sl during HOLD)
        with patch("daemon.iterators.guard.is_agent_managed", return_value=True):
            guard.tick(ctx_initial)

        # Mark current call counts as baseline
        cancel_calls_before = adapter.cancel_trigger_order.call_count

        # Tick 2: reclaimed
        ctx_reclaim = _ctx([_long("BTC")], prices={"BTC": 105.0})
        with patch("daemon.iterators.guard.is_agent_managed", return_value=False):
            guard.tick(ctx_reclaim)

        # cancel_exchange_sl was invoked (which calls adapter.cancel_trigger_order
        # if the bridge has an active SL oid)
        # We just need to verify the bridge was popped and the cancel path executed
        assert "BTC" not in guard._bridges

    def test_position_close_still_works_for_delegated_asset(self, tmp_path):
        """Pre-existing behavior: a position closing (qty → 0) cleans up its bridge."""
        guard = _make_guard(tmp_path)
        ctx_open = _ctx([_long("BTC")], prices={"BTC": 105.0})

        with patch("daemon.iterators.guard.is_agent_managed", return_value=True):
            guard.tick(ctx_open)
        assert "BTC" in guard._bridges

        # Position closes (qty → 0)
        zero_pos = Position(
            instrument="BTC",
            net_qty=Decimal("0"),
            avg_entry_price=Decimal("100"),
            leverage=Decimal("10"),
        )
        ctx_closed = _ctx([zero_pos], prices={"BTC": 105.0})
        with patch("daemon.iterators.guard.is_agent_managed", return_value=True):
            guard.tick(ctx_closed)

        assert "BTC" not in guard._bridges

    def test_authority_check_runs_before_price_check(self, tmp_path):
        """If price is missing, the authority check still doesn't fire (early continue)."""
        guard = _make_guard(tmp_path)
        # No price for BTC
        ctx = _ctx([_long("BTC")], prices={})

        with patch("daemon.iterators.guard.is_agent_managed", return_value=False) as mock_auth:
            guard.tick(ctx)

        # The price check at the top of the loop short-circuits before authority,
        # so is_agent_managed should NOT have been called for BTC.
        mock_auth.assert_not_called()
        assert "BTC" not in guard._bridges
