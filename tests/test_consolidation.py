"""Tests for common.consolidation — consolidation detection and ladder orders."""
import pytest
from common.consolidation import (
    Candle,
    ConsolidationConfig,
    ConsolidationDetector,
    ConsolidationResult,
    calculate_ladder_orders,
)


def _make_candle(open=100, high=101, low=99, close=100, volume=100, ts=0):
    return Candle(open=open, high=high, low=low, close=close, volume=volume, timestamp=ts)


class TestConsolidationDetector:
    """Test the multi-phase consolidation detection logic."""

    def test_not_started_returns_waiting(self):
        d = ConsolidationDetector()
        result = d.feed(_make_candle())
        assert result.action == "WAITING"

    def test_second_leg_down_aborts(self):
        d = ConsolidationDetector()
        d.start(dip_low=100.0, dip_high=110.0, spike_volume=5000)

        # Price breaks below dip low (100 - 0.2% = 99.8)
        candle = _make_candle(low=99.5, close=99.6, volume=1000)
        result = d.feed(candle)
        assert result.action == "ABORT"
        assert result.reason == "second_leg_down"
        assert not d.is_active

    def test_timeout_after_max_candles(self):
        cfg = ConsolidationConfig(max_wait_candles=5)
        d = ConsolidationDetector(cfg)
        d.start(dip_low=100.0, dip_high=110.0, spike_volume=5000)

        # Feed 5 candles with high volume (won't consolidate), staying above dip low
        for i in range(5):
            result = d.feed(_make_candle(low=100.5, high=102, close=101, volume=5000))

        assert result.action == "TIMEOUT"
        assert not d.is_active

    def test_volume_still_high_waits(self):
        d = ConsolidationDetector()
        d.start(dip_low=100.0, dip_high=110.0, spike_volume=10000)

        # Volume at 80% of spike — still too high, but price above dip low
        result = d.feed(_make_candle(low=100.5, high=102, close=101, volume=8000))
        assert result.action == "WAITING"
        assert "volume_still_high" in result.reason

    def test_range_still_wide_waits(self):
        d = ConsolidationDetector()
        d.start(dip_low=95.0, dip_high=110.0, spike_volume=10000)

        # Volume low but range still wide (5/15 = 33% > 30%), price above dip low
        result = d.feed(_make_candle(low=98, high=103, volume=2000))
        assert result.action == "WAITING"
        assert "range_still_wide" in result.reason

    def test_consolidation_confirmed_after_3_sideways(self):
        cfg = ConsolidationConfig(min_sideways_candles=3)
        d = ConsolidationDetector(cfg)
        d.start(dip_low=100.0, dip_high=110.0, spike_volume=10000)

        # Feed 3 quiet candles (low volume, narrow range)
        for i in range(2):
            result = d.feed(_make_candle(
                low=100.5, high=101.0, volume=2000, close=100.8
            ))
            assert result.action == "WAITING"
            assert "sideways" in result.reason

        # 3rd sideways candle triggers buy signal
        result = d.feed(_make_candle(
            low=100.5, high=101.0, volume=2000, close=100.7
        ))
        assert result.action == "BUY_SIGNAL"
        assert result.should_buy
        assert result.consolidation_level == 100.7
        assert result.drop_from_high_pct > 0
        assert not d.is_active

    def test_sideways_count_resets_on_volume_spike(self):
        cfg = ConsolidationConfig(min_sideways_candles=3)
        d = ConsolidationDetector(cfg)
        d.start(dip_low=100.0, dip_high=110.0, spike_volume=10000)

        # 2 quiet candles
        d.feed(_make_candle(low=100.5, high=101.0, volume=2000))
        d.feed(_make_candle(low=100.5, high=101.0, volume=2000))

        # Volume spike resets
        d.feed(_make_candle(low=100.5, high=101.0, volume=8000))

        # Need 3 more quiet candles now
        d.feed(_make_candle(low=100.5, high=101.0, volume=2000))
        d.feed(_make_candle(low=100.5, high=101.0, volume=2000))
        result = d.feed(_make_candle(low=100.5, high=101.0, volume=2000))
        assert result.action == "BUY_SIGNAL"

    def test_reset_clears_state(self):
        d = ConsolidationDetector()
        d.start(dip_low=100.0, dip_high=110.0, spike_volume=10000)
        assert d.is_active
        d.reset()
        assert not d.is_active

    def test_dip_low_boundary(self):
        """Price exactly at dip low should NOT abort (within tolerance)."""
        d = ConsolidationDetector()
        d.start(dip_low=100.0, dip_high=110.0, spike_volume=10000)

        # Low == dip_low exactly (within 0.2% tolerance)
        result = d.feed(_make_candle(low=100.0, volume=2000))
        assert result.action != "ABORT"

    def test_custom_config(self):
        cfg = ConsolidationConfig(
            volume_decline_ratio=0.3,
            range_compression_ratio=0.2,
            min_sideways_candles=2,
            max_wait_candles=10,
        )
        d = ConsolidationDetector(cfg)
        d.start(dip_low=100.0, dip_high=110.0, spike_volume=10000)

        # With stricter criteria, need volume < 30% and range < 20%
        # Volume at 25% = ok, range at 0.3/10 = 3% = ok
        d.feed(_make_candle(low=100.7, high=101.0, volume=2500))
        result = d.feed(_make_candle(low=100.7, high=101.0, volume=2500))
        assert result.action == "BUY_SIGNAL"


class TestLadderOrders:
    def test_default_three_tranches(self):
        orders = calculate_ladder_orders(100.0, 10.0)
        assert len(orders) == 3
        assert orders[0]["tranche"] == 1
        assert orders[1]["tranche"] == 2
        assert orders[2]["tranche"] == 3

    def test_sizes_sum_to_total(self):
        orders = calculate_ladder_orders(100.0, 10.0)
        total = sum(o["size"] for o in orders)
        assert abs(total - 10.0) < 0.001

    def test_prices_descend(self):
        orders = calculate_ladder_orders(100.0, 10.0)
        assert orders[0]["price"] > orders[1]["price"]
        assert orders[1]["price"] > orders[2]["price"]

    def test_first_tranche_at_consolidation_price(self):
        orders = calculate_ladder_orders(100.0, 10.0)
        assert orders[0]["price"] == 100.0

    def test_step_distance(self):
        cfg = ConsolidationConfig(ladder_step_pct=1.0)
        orders = calculate_ladder_orders(100.0, 10.0, config=cfg)
        # Second tranche at -1%, third at -2%
        assert abs(orders[1]["price"] - 99.0) < 0.01
        assert abs(orders[2]["price"] - 98.0) < 0.01

    def test_40_30_30_split(self):
        orders = calculate_ladder_orders(100.0, 10.0)
        assert abs(orders[0]["size"] - 4.0) < 0.001
        assert abs(orders[1]["size"] - 3.0) < 0.001
        assert abs(orders[2]["size"] - 3.0) < 0.001

    def test_custom_split(self):
        cfg = ConsolidationConfig(ladder_tranche_pcts=[0.5, 0.5])
        orders = calculate_ladder_orders(100.0, 10.0, config=cfg)
        assert len(orders) == 2
        assert abs(orders[0]["size"] - 5.0) < 0.001
        assert abs(orders[1]["size"] - 5.0) < 0.001
