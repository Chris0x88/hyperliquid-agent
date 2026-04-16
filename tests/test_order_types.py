"""Tests for managed order types and order book."""
from __future__ import annotations

import pytest

from common.models import MarketSnapshot, StrategyDecision
from exchange.order_types import BracketOrder, ConditionalOrder, PeggedOrder
from exchange.order_book import ManagedOrderBook


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _snap(mid: float, ts_ms: int = 1000) -> MarketSnapshot:
    return MarketSnapshot(
        instrument="ETH-PERP",
        mid_price=mid,
        bid=mid - 0.5,
        ask=mid + 0.5,
        spread_bps=1.0,
        timestamp_ms=ts_ms,
    )


# ---------------------------------------------------------------------------
# BracketOrder
# ---------------------------------------------------------------------------

class TestBracketOrder:
    def test_bracket_tp_long(self):
        """Long bracket triggers take-profit when price rises above TP."""
        b = BracketOrder(
            order_id="b1", instrument="ETH-PERP", direction="long",
            entry_price=2000.0, entry_size=1.0,
            take_profit_price=2100.0, stop_loss_price=1900.0,
        )
        result = b.on_tick(_snap(2100.0))
        assert result is not None
        assert result.side == "sell"
        assert result.size == 1.0
        assert result.meta["trigger"] == "take_profit"
        assert b.status == "tp_triggered"

    def test_bracket_sl_long(self):
        """Long bracket triggers stop-loss when price drops below SL."""
        b = BracketOrder(
            order_id="b2", instrument="ETH-PERP", direction="long",
            entry_price=2000.0, entry_size=1.0,
            take_profit_price=2100.0, stop_loss_price=1900.0,
        )
        result = b.on_tick(_snap(1900.0))
        assert result is not None
        assert result.side == "sell"
        assert result.meta["trigger"] == "stop_loss"
        assert b.status == "sl_triggered"

    def test_bracket_tp_short(self):
        """Short bracket triggers take-profit when price drops below TP."""
        b = BracketOrder(
            order_id="b3", instrument="ETH-PERP", direction="short",
            entry_price=2000.0, entry_size=1.0,
            take_profit_price=1900.0, stop_loss_price=2100.0,
        )
        result = b.on_tick(_snap(1900.0))
        assert result is not None
        assert result.side == "buy"
        assert result.meta["trigger"] == "take_profit"
        assert b.status == "tp_triggered"

    def test_bracket_sl_short(self):
        """Short bracket triggers stop-loss when price rises above SL."""
        b = BracketOrder(
            order_id="b4", instrument="ETH-PERP", direction="short",
            entry_price=2000.0, entry_size=1.0,
            take_profit_price=1900.0, stop_loss_price=2100.0,
        )
        result = b.on_tick(_snap(2100.0))
        assert result is not None
        assert result.side == "buy"
        assert result.meta["trigger"] == "stop_loss"
        assert b.status == "sl_triggered"

    def test_bracket_no_trigger(self):
        """Price between TP and SL -- no trigger."""
        b = BracketOrder(
            order_id="b5", instrument="ETH-PERP", direction="long",
            entry_price=2000.0, entry_size=1.0,
            take_profit_price=2100.0, stop_loss_price=1900.0,
        )
        result = b.on_tick(_snap(2000.0))
        assert result is None
        assert b.status == "active"


# ---------------------------------------------------------------------------
# ConditionalOrder
# ---------------------------------------------------------------------------

class TestConditionalOrder:
    def test_conditional_above(self):
        """Conditional triggers when price crosses above threshold."""
        c = ConditionalOrder(
            order_id="c1", instrument="ETH-PERP",
            trigger_price=2050.0, trigger_condition="above",
            child_side="buy", child_size=0.5,
        )
        # Below threshold -- no trigger
        assert c.on_tick(_snap(2000.0)) is None
        assert c.status == "pending"

        # At/above threshold -- triggers
        result = c.on_tick(_snap(2050.0))
        assert result is not None
        assert result.side == "buy"
        assert result.size == 0.5
        assert result.meta["trigger"] == "conditional"
        assert c.status == "triggered"

    def test_conditional_below(self):
        """Conditional triggers when price drops below threshold."""
        c = ConditionalOrder(
            order_id="c2", instrument="ETH-PERP",
            trigger_price=1950.0, trigger_condition="below",
            child_side="sell", child_size=0.3,
        )
        # Above threshold -- no trigger
        assert c.on_tick(_snap(2000.0)) is None

        # At/below threshold -- triggers
        result = c.on_tick(_snap(1950.0))
        assert result is not None
        assert result.side == "sell"
        assert result.size == 0.3
        assert c.status == "triggered"

    def test_conditional_expiry(self):
        """Conditional expires after expiry_ms."""
        c = ConditionalOrder(
            order_id="c3", instrument="ETH-PERP",
            trigger_price=2050.0, trigger_condition="above",
            child_side="buy", child_size=1.0,
            expiry_ms=5000, created_at_ms=1000,
        )
        # Tick past expiry -- should expire without triggering
        result = c.on_tick(_snap(2100.0, ts_ms=6000))
        assert result is None
        assert c.status == "expired"


# ---------------------------------------------------------------------------
# PeggedOrder
# ---------------------------------------------------------------------------

class TestPeggedOrder:
    def test_pegged_buy(self):
        """Pegged buy produces bid below mid."""
        p = PeggedOrder(
            order_id="p1", instrument="ETH-PERP",
            side="buy", size=1.0, offset_bps=10.0,
        )
        result = p.on_tick(_snap(2000.0))
        assert result is not None
        assert result.side == "buy"
        # 10 bps of 2000 = 2.0, so price = 2000 - 2 = 1998
        assert result.limit_price == 1998.0

    def test_pegged_sell(self):
        """Pegged sell produces ask above mid."""
        p = PeggedOrder(
            order_id="p2", instrument="ETH-PERP",
            side="sell", size=1.0, offset_bps=10.0,
        )
        result = p.on_tick(_snap(2000.0))
        assert result is not None
        assert result.side == "sell"
        # 10 bps of 2000 = 2.0, so price = 2000 + 2 = 2002
        assert result.limit_price == 2002.0

    def test_pegged_expiry(self):
        """Pegged expires after max_ticks."""
        p = PeggedOrder(
            order_id="p3", instrument="ETH-PERP",
            side="buy", size=1.0, offset_bps=5.0,
            max_ticks=2,
        )
        # Tick 1 -- active
        r1 = p.on_tick(_snap(2000.0))
        assert r1 is not None
        assert p.status == "active"

        # Tick 2 -- active
        r2 = p.on_tick(_snap(2000.0))
        assert r2 is not None
        assert p.status == "active"

        # Tick 3 -- expired (ticks_elapsed=3 > max_ticks=2)
        r3 = p.on_tick(_snap(2000.0))
        assert r3 is None
        assert p.status == "expired"


# ---------------------------------------------------------------------------
# ManagedOrderBook
# ---------------------------------------------------------------------------

class TestManagedOrderBook:
    def test_order_book_multi(self):
        """Order book with multiple types, one tick, correct triggers."""
        book = ManagedOrderBook()

        # Bracket that should TP at 2100
        book.add(BracketOrder(
            order_id="b1", instrument="ETH-PERP", direction="long",
            entry_price=2000.0, entry_size=1.0,
            take_profit_price=2100.0, stop_loss_price=1900.0,
        ))
        # Conditional that should NOT trigger (needs price above 2200)
        book.add(ConditionalOrder(
            order_id="c1", instrument="ETH-PERP",
            trigger_price=2200.0, trigger_condition="above",
            child_side="buy", child_size=0.5,
        ))
        # Pegged order -- always emits
        book.add(PeggedOrder(
            order_id="p1", instrument="ETH-PERP",
            side="buy", size=0.1, offset_bps=5.0,
        ))

        assert book.count == 3

        decisions = book.on_tick(_snap(2100.0))
        # Bracket TP triggers + pegged emits = 2 decisions
        assert len(decisions) == 2
        triggers = {d.meta.get("trigger") for d in decisions}
        assert "take_profit" in triggers
        assert "pegged" in triggers

    def test_order_book_cleanup(self):
        """Triggered/expired orders are removed from the book after tick."""
        book = ManagedOrderBook()

        book.add(BracketOrder(
            order_id="b1", instrument="ETH-PERP", direction="long",
            entry_price=2000.0, entry_size=1.0,
            take_profit_price=2100.0, stop_loss_price=1900.0,
        ))
        book.add(ConditionalOrder(
            order_id="c1", instrument="ETH-PERP",
            trigger_price=2050.0, trigger_condition="above",
            child_side="buy", child_size=0.5,
        ))

        assert book.count == 2

        # Both should trigger at 2100
        decisions = book.on_tick(_snap(2100.0))
        assert len(decisions) == 2

        # Both should be cleaned up
        assert book.count == 0
        assert book.get("b1") is None
        assert book.get("c1") is None
