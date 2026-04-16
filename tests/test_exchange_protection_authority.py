"""Tests for the H1 authority gate in ExchangeProtectionIterator.

Closes the LATENT-REBALANCE gap from the 2026-04-07 verification ledger:
exchange_protection now skips positions whose asset is not delegated to
the agent, and cancels any previously-placed SL when authority is reclaimed.

Production runs in WATCH tier where exchange_protection does not execute,
so this is a tier-promotion gate, not an active production fix. The tests
exercise the iterator directly (not via the daemon).
"""
from __future__ import annotations

from decimal import Decimal
from typing import Any, Dict, List
from unittest.mock import patch

import pytest

from cli.daemon.context import TickContext
from cli.daemon.iterators.exchange_protection import (
    ExchangeProtectionIterator,
    RuinProtectionConfig,
)
from exchange.position_tracker import Position


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _RecordingAdapter:
    """Minimal stand-in for the venue adapter — records every SL call."""

    def __init__(self) -> None:
        self.placed: List[Dict[str, Any]] = []
        self.cancelled: List[Dict[str, Any]] = []
        self._next_oid = 1000

    def place_trigger_order(self, instrument: str, side: str, size: float, trigger_price: float) -> str:
        oid = str(self._next_oid)
        self._next_oid += 1
        self.placed.append({
            "instrument": instrument,
            "side": side,
            "size": size,
            "trigger_price": trigger_price,
            "oid": oid,
        })
        return oid

    def cancel_trigger_order(self, instrument: str, oid: str) -> bool:
        self.cancelled.append({"instrument": instrument, "oid": oid})
        return True


def _long(inst: str, qty: float, entry: float, liq: float, lev: int = 10) -> Position:
    return Position(
        instrument=inst,
        net_qty=Decimal(str(qty)),
        avg_entry_price=Decimal(str(entry)),
        liquidation_price=Decimal(str(liq)),
        leverage=Decimal(str(lev)),
    )


def _short(inst: str, qty: float, entry: float, liq: float, lev: int = 10) -> Position:
    return Position(
        instrument=inst,
        net_qty=Decimal(str(-abs(qty))),
        avg_entry_price=Decimal(str(entry)),
        liquidation_price=Decimal(str(liq)),
        leverage=Decimal(str(lev)),
    )


def _ctx(positions: List[Position]) -> TickContext:
    c = TickContext()
    c.positions = positions
    return c


def _make_iterator() -> tuple[ExchangeProtectionIterator, _RecordingAdapter]:
    adapter = _RecordingAdapter()
    it = ExchangeProtectionIterator(adapter=adapter, config=RuinProtectionConfig())
    # Bypass throttle so every tick() call is allowed to do work
    it._last_tick = -1e9
    return it, adapter


# ---------------------------------------------------------------------------
# Authority gate tests
# ---------------------------------------------------------------------------


class TestAuthorityGate:
    def test_agent_managed_gets_sl_placed(self):
        """An 'agent' authority position gets a ruin-prevention SL placed."""
        it, adapter = _make_iterator()
        ctx = _ctx([_long("BTC", 1.0, 100.0, 90.0)])

        with patch("cli.daemon.iterators.exchange_protection.is_agent_managed", return_value=True):
            it.tick(ctx)

        assert len(adapter.placed) == 1
        order = adapter.placed[0]
        assert order["instrument"] == "BTC"
        assert order["side"] == "sell"  # long → sell to close
        # SL = 90 * 1.02 = 91.8
        assert order["trigger_price"] == pytest.approx(91.8)
        assert "BTC" in it._tracked

    def test_manual_position_is_skipped(self):
        """A 'manual' authority position must NOT get an SL placed."""
        it, adapter = _make_iterator()
        ctx = _ctx([_long("GOLD", 0.5, 2000.0, 1800.0)])

        with patch("cli.daemon.iterators.exchange_protection.is_agent_managed", return_value=False):
            it.tick(ctx)

        assert adapter.placed == []
        assert "GOLD" not in it._tracked

    def test_off_position_is_skipped(self):
        """An 'off' authority position is also skipped (is_agent_managed=False)."""
        it, adapter = _make_iterator()
        ctx = _ctx([_long("MEME", 100.0, 1.0, 0.5)])

        with patch("cli.daemon.iterators.exchange_protection.is_agent_managed", return_value=False):
            it.tick(ctx)

        assert adapter.placed == []
        assert "MEME" not in it._tracked

    def test_mixed_authority_only_agent_gets_sl(self):
        """When the portfolio has agent + manual positions, only agent gets SLs."""
        it, adapter = _make_iterator()
        ctx = _ctx([
            _long("BTC", 1.0, 100.0, 90.0),
            _long("GOLD", 0.5, 2000.0, 1800.0),
            _short("xyz:BRENTOIL", 5.0, 80.0, 95.0),
        ])

        # BTC and BRENTOIL are agent-managed, GOLD is not
        def fake_is_agent_managed(asset: str) -> bool:
            return asset in ("BTC", "xyz:BRENTOIL")

        with patch(
            "cli.daemon.iterators.exchange_protection.is_agent_managed",
            side_effect=fake_is_agent_managed,
        ):
            it.tick(ctx)

        placed_insts = sorted(o["instrument"] for o in adapter.placed)
        assert placed_insts == ["BTC", "xyz:BRENTOIL"]
        assert "GOLD" not in it._tracked

    def test_authority_reclaim_cancels_existing_sl(self):
        """When authority is reclaimed (agent → manual), the existing SL is cancelled."""
        it, adapter = _make_iterator()
        ctx_initial = _ctx([_long("BTC", 1.0, 100.0, 90.0)])

        # Tick 1: BTC is agent-managed → SL placed
        with patch("cli.daemon.iterators.exchange_protection.is_agent_managed", return_value=True):
            it.tick(ctx_initial)
        assert len(adapter.placed) == 1
        original_oid = adapter.placed[0]["oid"]
        assert "BTC" in it._tracked
        assert it._tracked["BTC"].sl_oid == original_oid

        # Reset throttle to allow another tick immediately
        it._last_tick = -1e9

        # Tick 2: BTC is now manual → SL must be cancelled
        ctx_reclaim = _ctx([_long("BTC", 1.0, 100.0, 90.0)])
        with patch("cli.daemon.iterators.exchange_protection.is_agent_managed", return_value=False):
            it.tick(ctx_reclaim)

        # Cancel was called for the original OID
        assert any(c["oid"] == original_oid for c in adapter.cancelled)
        # The instrument was removed from tracking
        assert "BTC" not in it._tracked
        # The cleanup alert references reclaim or close
        cleanup_alerts = [
            a for a in ctx_reclaim.alerts
            if a.source == "exchange_protection" and "BTC" in a.message
        ]
        assert any("authority reclaimed" in a.message or "closed" in a.message for a in cleanup_alerts)

    def test_zero_qty_position_skipped_regardless_of_authority(self):
        """A position with net_qty == 0 is skipped even if authority is agent."""
        it, adapter = _make_iterator()
        ctx = _ctx([
            Position(
                instrument="BTC",
                net_qty=Decimal("0"),
                avg_entry_price=Decimal("100"),
                liquidation_price=Decimal("90"),
                leverage=Decimal("10"),
            ),
        ])

        with patch("cli.daemon.iterators.exchange_protection.is_agent_managed", return_value=True):
            it.tick(ctx)

        assert adapter.placed == []
        assert "BTC" not in it._tracked

    def test_position_close_still_cancels_sl(self):
        """Pre-existing behavior: a position closing (qty → 0) cancels its SL."""
        it, adapter = _make_iterator()

        # Tick 1: open BTC long, agent-managed → SL placed
        ctx_open = _ctx([_long("BTC", 1.0, 100.0, 90.0)])
        with patch("cli.daemon.iterators.exchange_protection.is_agent_managed", return_value=True):
            it.tick(ctx_open)
        assert "BTC" in it._tracked
        original_oid = it._tracked["BTC"].sl_oid

        it._last_tick = -1e9

        # Tick 2: BTC position closed (no positions in ctx) → SL cancelled
        ctx_closed = _ctx([])
        with patch("cli.daemon.iterators.exchange_protection.is_agent_managed", return_value=True):
            it.tick(ctx_closed)

        assert any(c["oid"] == original_oid for c in adapter.cancelled)
        assert "BTC" not in it._tracked
