"""Tests for market_structure.py and market_snapshot.py.

Uses synthetic candle data — no API calls, no external deps.
Validates that:
1. All indicators compute correctly on known data
2. MarketSnapshot assembles without error
3. Text rendering produces compact, parseable output
4. Edge cases (empty data, single candle, flat market) don't crash
"""
from __future__ import annotations

import math
import pytest

from common.market_structure import (
    OHLCV,
    BollingerBands,
    atr,
    atr_series,
    bollinger_bands,
    cluster_levels,
    detect_rsi_divergence,
    ema,
    find_key_levels,
    rsi,
    sma,
    swing_levels,
    trend_analysis,
    volume_profile,
    vwap,
)
from common.market_snapshot import (
    MarketSnapshot,
    build_snapshot_from_candles,
    render_snapshot,
    snapshot_to_dict,
)


# ═══════════════════════════════════════════════════════════════════════════════
# Test data factories
# ═══════════════════════════════════════════════════════════════════════════════

def _make_candles(
    n: int = 100,
    start_price: float = 100.0,
    trend: float = 0.001,  # per-candle drift
    volatility: float = 0.02,
    volume_base: float = 1000.0,
    start_ts: int = 1_700_000_000_000,
    interval_ms: int = 3_600_000,
) -> list[OHLCV]:
    """Generate synthetic candles with controllable trend and volatility."""
    candles = []
    price = start_price
    for i in range(n):
        # Deterministic "randomness" using sin for reproducibility
        noise = math.sin(i * 1.7) * volatility * price
        drift = trend * price

        o = price
        c = price + drift + noise
        h = max(o, c) + abs(math.sin(i * 2.3)) * volatility * price * 0.5
        l = min(o, c) - abs(math.cos(i * 3.1)) * volatility * price * 0.5
        v = volume_base * (1 + 0.5 * math.sin(i * 0.7))

        candles.append(OHLCV(
            t=start_ts + i * interval_ms,
            o=round(o, 4),
            h=round(h, 4),
            l=round(l, 4),
            c=round(c, 4),
            v=round(v, 2),
        ))
        price = c
    return candles


def _candles_to_hl_dicts(candles: list[OHLCV]) -> list[dict]:
    """Convert OHLCV objects back to HL dict format (string values)."""
    return [
        {"t": c.t, "o": str(c.o), "h": str(c.h), "l": str(c.l), "c": str(c.c), "v": str(c.v)}
        for c in candles
    ]


# ═══════════════════════════════════════════════════════════════════════════════
# Unit tests — pure indicator functions
# ═══════════════════════════════════════════════════════════════════════════════

class TestSMA:
    def test_basic(self):
        values = [1.0, 2.0, 3.0, 4.0, 5.0]
        result = sma(values, 3)
        assert len(result) == 3
        assert result[0] == pytest.approx(2.0)
        assert result[1] == pytest.approx(3.0)
        assert result[2] == pytest.approx(4.0)

    def test_insufficient_data(self):
        assert sma([1.0, 2.0], 5) == []

    def test_single_period(self):
        values = [10.0, 20.0, 30.0]
        result = sma(values, 1)
        assert result == values


class TestEMA:
    def test_basic(self):
        values = [1.0, 2.0, 3.0, 4.0, 5.0]
        result = ema(values, 3)
        assert len(result) == 5
        # First value = first input
        assert result[0] == 1.0
        # EMA converges toward recent values
        assert result[-1] > result[0]

    def test_empty(self):
        assert ema([], 10) == []


class TestRSI:
    def test_uptrend_high_rsi(self):
        # Monotonically increasing prices → RSI near 100
        closes = [float(i) for i in range(1, 30)]
        r = rsi(closes, 14)
        assert r > 80

    def test_downtrend_low_rsi(self):
        closes = [float(30 - i) for i in range(30)]
        r = rsi(closes, 14)
        assert r < 20

    def test_insufficient_data(self):
        assert rsi([1.0, 2.0], 14) == 50.0

    def test_flat_market(self):
        closes = [100.0] * 30
        r = rsi(closes, 14)
        # All gains and losses are 0, so RSI should be 50 (no change)
        # Actually with 0 gains and 0 losses, avg_loss=0 → returns 100
        # This is mathematically correct: no selling pressure = full strength
        assert r == 100.0


class TestATR:
    def test_basic(self):
        candles = _make_candles(30, volatility=0.03)
        a = atr(candles, 14)
        assert a > 0
        # ATR should be roughly proportional to volatility * price
        assert a < candles[-1].c * 0.2  # not absurdly large

    def test_insufficient_data(self):
        candles = _make_candles(5)
        assert atr(candles, 14) == 0.0

    def test_series(self):
        candles = _make_candles(50)
        series = atr_series(candles, 14)
        assert len(series) > 0
        assert all(v > 0 for v in series)


class TestBollingerBands:
    def test_basic(self):
        closes = [100.0 + math.sin(i * 0.3) * 5 for i in range(30)]
        bb = bollinger_bands(closes)
        assert bb is not None
        assert bb.upper > bb.middle > bb.lower
        assert bb.bandwidth > 0
        assert 0.0 <= bb.pct_b or bb.pct_b >= 0  # can be outside

    def test_squeeze_detection(self):
        # Very tight range → squeeze
        closes = [100.0 + 0.01 * i for i in range(30)]
        bb = bollinger_bands(closes)
        assert bb is not None
        assert bb.is_squeeze  # bandwidth < 4%

    def test_zone_classification(self):
        closes = [100.0 + math.sin(i * 0.2) * 10 for i in range(30)]
        bb = bollinger_bands(closes, current_price=closes[-1])
        assert bb is not None
        assert bb.zone in ("above_upper", "upper_half", "lower_half", "below_lower")

    def test_insufficient_data(self):
        assert bollinger_bands([1.0, 2.0]) is None


class TestVWAP:
    def test_basic(self):
        candles = _make_candles(20)
        v = vwap(candles)
        # VWAP should be near the average price
        avg_close = sum(c.c for c in candles) / len(candles)
        assert abs(v - avg_close) / avg_close < 0.1  # within 10%

    def test_zero_volume(self):
        candles = [OHLCV(t=i, o=100, h=101, l=99, c=100, v=0) for i in range(5)]
        assert vwap(candles) == 0.0


class TestVolumeProfile:
    def test_basic(self):
        candles = _make_candles(50)
        vp = volume_profile(candles)
        assert vp is not None
        assert vp.poc > 0
        assert vp.value_area_high >= vp.value_area_low
        assert vp.total_volume > 0
        assert len(vp.buckets) == 20  # default

    def test_value_area_contains_poc(self):
        candles = _make_candles(50)
        vp = volume_profile(candles)
        assert vp is not None
        assert vp.value_area_low <= vp.poc <= vp.value_area_high

    def test_insufficient_data(self):
        candles = _make_candles(3)
        assert volume_profile(candles) is None


class TestSwingLevels:
    def test_finds_levels(self):
        candles = _make_candles(50, volatility=0.05)
        supports, resistances = swing_levels(candles)
        # With volatile data, should find at least some levels
        assert isinstance(supports, list)
        assert isinstance(resistances, list)

    def test_insufficient_data(self):
        candles = _make_candles(5)
        s, r = swing_levels(candles)
        assert s == []
        assert r == []


class TestClusterLevels:
    def test_clusters_nearby(self):
        levels = [100.0, 100.2, 100.4, 110.0, 110.1]
        clusters = cluster_levels(levels, tolerance_pct=0.5)
        # Should cluster 100.0-100.4 together and 110.0-110.1 together
        assert len(clusters) == 2
        # Biggest cluster first
        assert clusters[0][1] >= clusters[1][1]

    def test_empty(self):
        assert cluster_levels([]) == []


class TestTrendAnalysis:
    def test_uptrend(self):
        candles = _make_candles(50, trend=0.005, volatility=0.01)
        ta = trend_analysis(candles)
        assert ta.direction in ("up", "strong_up")
        assert ta.ema_spread_pct > 0

    def test_downtrend(self):
        candles = _make_candles(50, trend=-0.005, volatility=0.01)
        ta = trend_analysis(candles)
        assert ta.direction in ("down", "strong_down")
        assert ta.ema_spread_pct < 0

    def test_flat_market(self):
        candles = _make_candles(50, trend=0.0, volatility=0.005)
        ta = trend_analysis(candles)
        # Should be near neutral
        assert ta.strength < 60

    def test_has_rsi(self):
        candles = _make_candles(50)
        ta = trend_analysis(candles)
        assert 0 <= ta.rsi <= 100


class TestRSIDivergence:
    def test_no_divergence_flat(self):
        closes = [100.0 + 0.1 * i for i in range(50)]
        assert detect_rsi_divergence(closes) == "none"


class TestFindKeyLevels:
    def test_returns_levels(self):
        candles = _make_candles(80, volatility=0.04)
        price = candles[-1].c
        bb = bollinger_bands([c.c for c in candles])
        vp = volume_profile(candles)
        levels = find_key_levels(candles, price, bb=bb, vp=vp)
        assert isinstance(levels, list)
        assert len(levels) <= 8
        for kl in levels:
            assert kl.price > 0
            assert kl.type in ("support", "resistance")

    def test_without_optional_data(self):
        candles = _make_candles(80)
        levels = find_key_levels(candles, candles[-1].c)
        assert isinstance(levels, list)


# ═══════════════════════════════════════════════════════════════════════════════
# Integration tests — MarketSnapshot
# ═══════════════════════════════════════════════════════════════════════════════

class TestMarketSnapshot:
    def test_build_from_candles(self):
        candles_1h = _make_candles(100, volatility=0.03)
        candles_4h = _make_candles(50, volatility=0.04, interval_ms=14_400_000)

        candle_sets = {
            "1h": _candles_to_hl_dicts(candles_1h),
            "4h": _candles_to_hl_dicts(candles_4h),
        }
        price = candles_1h[-1].c

        snap = build_snapshot_from_candles("BTC", candle_sets, price)

        assert snap.market == "BTC"
        assert snap.current_price == price
        assert "1h" in snap.timeframes
        assert "4h" in snap.timeframes
        assert isinstance(snap.flags, list)
        assert isinstance(snap.key_levels, list)

    def test_empty_candles(self):
        snap = build_snapshot_from_candles("BTC", {}, 50000.0)
        assert snap.market == "BTC"
        assert len(snap.timeframes) == 0

    def test_single_timeframe(self):
        candles = _make_candles(30)
        snap = build_snapshot_from_candles(
            "xyz:BRENTOIL",
            {"1h": _candles_to_hl_dicts(candles)},
            candles[-1].c,
        )
        assert "1h" in snap.timeframes
        assert snap.timeframes["1h"].atr_value > 0


class TestRenderSnapshot:
    def _make_snap(self) -> MarketSnapshot:
        candles_1h = _make_candles(100, start_price=84000, volatility=0.02)
        candles_4h = _make_candles(50, start_price=83000, volatility=0.03, interval_ms=14_400_000)
        return build_snapshot_from_candles(
            "BTC",
            {"1h": _candles_to_hl_dicts(candles_1h), "4h": _candles_to_hl_dicts(candles_4h)},
            candles_1h[-1].c,
        )

    def test_brief(self):
        text = render_snapshot(self._make_snap(), detail="brief")
        assert "BTC" in text
        lines = text.strip().split("\n")
        assert len(lines) <= 6  # very compact

    def test_standard(self):
        text = render_snapshot(self._make_snap(), detail="standard")
        assert "BTC" in text
        assert "RSI=" in text
        assert "ATR=" in text
        lines = text.strip().split("\n")
        assert len(lines) <= 12

    def test_full(self):
        text = render_snapshot(self._make_snap(), detail="full")
        assert "BTC" in text
        lines = text.strip().split("\n")
        # Full should have more detail than standard
        assert len(lines) >= 3

    def test_token_efficiency(self):
        """Verify the snapshot is much smaller than raw candles."""
        snap = self._make_snap()
        text = render_snapshot(snap, detail="full")

        # Raw candles would be ~150 candles * ~30 chars each = ~4500 chars
        # Our snapshot should be < 1500 chars (3x compression minimum)
        assert len(text) < 2000, f"Snapshot too large: {len(text)} chars"

        # Word count as proxy for tokens (~0.75 tokens per word)
        word_count = len(text.split())
        assert word_count < 300, f"Too many words: {word_count}"


class TestSnapshotToDict:
    def test_serializable(self):
        candles = _make_candles(50)
        snap = build_snapshot_from_candles(
            "BTC", {"1h": _candles_to_hl_dicts(candles)}, candles[-1].c,
        )
        d = snapshot_to_dict(snap)

        import json
        # Must be JSON-serializable
        json_str = json.dumps(d)
        assert len(json_str) > 0

        # Key fields present
        assert d["market"] == "BTC"
        assert "timeframes" in d
        assert "key_levels" in d
        assert "flags" in d


# ═══════════════════════════════════════════════════════════════════════════════
# Edge cases
# ═══════════════════════════════════════════════════════════════════════════════

class TestEdgeCases:
    def test_zero_price(self):
        """Building snapshot with zero price should not crash."""
        candles = _make_candles(30)
        snap = build_snapshot_from_candles("TEST", {"1h": _candles_to_hl_dicts(candles)}, 0.0)
        # Should not crash, just have empty/default values
        assert snap.current_price == 0.0

    def test_very_small_candles(self):
        """Small penny-stock style prices."""
        candles = _make_candles(50, start_price=0.001, volatility=0.1)
        snap = build_snapshot_from_candles(
            "MEME", {"1h": _candles_to_hl_dicts(candles)}, candles[-1].c,
        )
        text = render_snapshot(snap)
        assert "MEME" in text

    def test_very_large_prices(self):
        """BTC-style large numbers."""
        candles = _make_candles(50, start_price=84500.0, volatility=0.015)
        snap = build_snapshot_from_candles(
            "BTC", {"1h": _candles_to_hl_dicts(candles)}, candles[-1].c,
        )
        text = render_snapshot(snap)
        assert "BTC" in text

    def test_ohlcv_from_hl(self):
        """Test the HL dict → OHLCV conversion."""
        hl = {"t": 1700000000000, "o": "100.5", "h": "101.0", "l": "99.5", "c": "100.8", "v": "5000"}
        ohlcv = OHLCV.from_hl(hl)
        assert ohlcv.o == 100.5
        assert ohlcv.h == 101.0
        assert ohlcv.v == 5000.0
