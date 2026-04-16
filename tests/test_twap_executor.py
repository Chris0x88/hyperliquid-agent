"""Tests for execution/twap.py — TWAP execution engine."""
import random

import pytest

from common.models import MarketSnapshot
from exchange.parent_order import ParentOrder
from exchange.twap import TWAPExecutor, ChildSlice


def _make_snapshot(mid=2500.0, bid=2499.0, ask=2501.0, ts=1000) -> MarketSnapshot:
    return MarketSnapshot(
        instrument="ETH-PERP",
        mid_price=mid,
        bid=bid,
        ask=ask,
        timestamp_ms=ts,
    )


def _make_order(**kwargs) -> ParentOrder:
    defaults = dict(
        instrument="ETH-PERP",
        side="buy",
        target_qty=10.0,
        algo="twap",
        duration_ticks=5,
        urgency=1.0,  # max urgency for deterministic tests (no skips)
    )
    defaults.update(kwargs)
    return ParentOrder(**defaults)


class TestSubmitAndTick:
    def test_submit_and_tick_produces_slices(self):
        """Submit an order, tick N times, verify slices come out."""
        random.seed(42)
        exe = TWAPExecutor()
        order = _make_order(target_qty=10.0, duration_ticks=5, urgency=1.0)
        exe.submit(order)

        snap = _make_snapshot()
        all_slices = []
        for _ in range(5):
            slices = exe.on_tick(snap)
            all_slices.extend(slices)

        assert len(all_slices) > 0
        for s in all_slices:
            assert s.instrument == "ETH-PERP"
            assert s.side == "buy"
            assert s.size > 0
            assert s.parent_order_id == order.order_id

    def test_buy_uses_ask_price(self):
        random.seed(42)
        exe = TWAPExecutor()
        order = _make_order(side="buy", urgency=1.0)
        exe.submit(order)
        slices = exe.on_tick(_make_snapshot(ask=2505.0))
        assert len(slices) == 1
        assert slices[0].price == 2505.0

    def test_sell_uses_bid_price(self):
        random.seed(42)
        exe = TWAPExecutor()
        order = _make_order(side="sell", urgency=1.0)
        exe.submit(order)
        slices = exe.on_tick(_make_snapshot(bid=2495.0))
        assert len(slices) == 1
        assert slices[0].price == 2495.0


class TestFillTracking:
    def test_record_fills_updates_progress(self):
        """Submit, tick, record fills, verify progress and completion."""
        random.seed(42)
        exe = TWAPExecutor()
        order = _make_order(target_qty=10.0, urgency=1.0)
        exe.submit(order)

        snap = _make_snapshot()
        slices = exe.on_tick(snap)
        assert len(slices) == 1

        # Record a partial fill
        exe.record_fill(order.order_id, 3.0, 2501.0, 1000)
        assert order.filled_qty == 3.0
        assert order.progress == pytest.approx(0.3)
        assert order.status == "active"

    def test_fill_completes_order(self):
        exe = TWAPExecutor()
        order = _make_order(target_qty=5.0)
        exe.submit(order)

        exe.record_fill(order.order_id, 5.0, 2500.0, 1000)
        assert order.status == "complete"
        assert order.is_complete is True
        assert order.remaining_qty <= 0


class TestUrgencyAffectsSizing:
    def test_higher_urgency_larger_slices(self):
        """Higher urgency should produce larger front slices."""
        random.seed(42)
        exe_high = TWAPExecutor()
        order_high = _make_order(target_qty=10.0, urgency=1.0, duration_ticks=10)
        exe_high.submit(order_high)

        random.seed(42)
        exe_low = TWAPExecutor()
        order_low = _make_order(target_qty=10.0, urgency=0.0, duration_ticks=10)
        exe_low.submit(order_low)

        snap = _make_snapshot()

        # Run enough ticks to get slices from both (low urgency may skip)
        high_sizes = []
        low_sizes = []
        random.seed(42)
        for _ in range(10):
            for s in exe_high.on_tick(snap):
                high_sizes.append(s.size)

        random.seed(42)
        for _ in range(10):
            for s in exe_low.on_tick(snap):
                low_sizes.append(s.size)

        # High urgency first slice should be larger than low urgency first slice
        # (when both produce a slice)
        if high_sizes and low_sizes:
            assert high_sizes[0] > low_sizes[0]


class TestSkipProbability:
    def test_zero_urgency_can_skip(self):
        """With urgency=0, some ticks should produce no slice (skip_prob=0.2)."""
        random.seed(1)  # pick a seed that triggers skips
        exe = TWAPExecutor()
        order = _make_order(target_qty=100.0, urgency=0.0, duration_ticks=50)
        exe.submit(order)

        snap = _make_snapshot()
        tick_results = []
        for _ in range(50):
            slices = exe.on_tick(snap)
            tick_results.append(len(slices))

        # With skip_prob=0.2, expect some ticks with 0 slices
        skipped = tick_results.count(0)
        assert skipped > 0, "Expected some skipped ticks with urgency=0"

    def test_max_urgency_no_skips(self):
        """With urgency=1.0, skip_prob=0 so every tick produces a slice."""
        random.seed(42)
        exe = TWAPExecutor()
        order = _make_order(target_qty=100.0, urgency=1.0, duration_ticks=10)
        exe.submit(order)

        snap = _make_snapshot()
        for _ in range(10):
            slices = exe.on_tick(snap)
            assert len(slices) == 1


class TestCompletesWhenFilled:
    def test_completed_order_removed_from_active(self):
        """After all qty filled, order marked complete and removed on next tick."""
        exe = TWAPExecutor()
        order = _make_order(target_qty=5.0)
        exe.submit(order)
        assert exe.active_count == 1

        exe.record_fill(order.order_id, 5.0, 2500.0, 1000)
        assert order.status == "complete"

        # Next tick should clean it up
        snap = _make_snapshot()
        exe.on_tick(snap)
        assert exe.active_count == 0


class TestRemainingQtyCapsSlice:
    def test_final_slice_never_exceeds_remaining(self):
        """After partial fills, slice size is capped at remaining_qty."""
        random.seed(42)
        exe = TWAPExecutor()
        order = _make_order(target_qty=2.0, urgency=1.0, duration_ticks=5)
        exe.submit(order)

        snap = _make_snapshot()

        # Fill most of it
        exe.record_fill(order.order_id, 1.9, 2500.0, 1000)
        assert order.remaining_qty == pytest.approx(0.1)

        # Next slice should be <= 0.1
        slices = exe.on_tick(snap)
        assert len(slices) == 1
        assert slices[0].size <= order.remaining_qty + 1e-9  # float tolerance
