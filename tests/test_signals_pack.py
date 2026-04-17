"""Tests for Phase 3 signals pack — accumulation/distribution toolkit."""
from __future__ import annotations

from typing import Any

from common.signals import compute


def _bar(t: int, o: float, h: float, l: float, c: float, v: float) -> dict[str, Any]:
    return {"t": t, "o": o, "h": h, "l": l, "c": c, "v": v}


# ── CVD ──────────────────────────────────────────────────────────────────


class TestCVD:
    def test_empty_input(self):
        r = compute("cvd", [])
        assert r.values == []
        assert "reason" in r.meta

    def test_up_bar_adds_volume(self):
        # close > open → buy-side
        r = compute("cvd", [_bar(1, 100, 101, 99, 101, 500)])
        assert r.values == [[1, 500.0]]

    def test_down_bar_subtracts_volume(self):
        r = compute("cvd", [_bar(1, 100, 101, 99, 99, 500)])
        assert r.values == [[1, -500.0]]

    def test_doji_is_zero(self):
        r = compute("cvd", [_bar(1, 100, 101, 99, 100, 500)])
        assert r.values == [[1, 0.0]]

    def test_cumulative(self):
        candles = [
            _bar(1, 100, 101, 99, 101, 500),  # up +500
            _bar(2, 101, 102, 100, 100, 300),  # down -300
            _bar(3, 100, 101, 99, 101, 200),  # up +200
        ]
        r = compute("cvd", candles)
        assert [v for _, v in r.values] == [500.0, 200.0, 400.0]
        assert r.meta["current"] == 400.0

    def test_string_valued_candles(self):
        r = compute("cvd", [{"t": 1, "o": "100", "h": "101", "l": "99", "c": "101", "v": "500"}])
        assert r.values == [[1, 500.0]]

    def test_smoke_meta_populated(self):
        candles = [_bar(i, 100, 101, 99, 100 + (i % 2), 1000) for i in range(1, 6)]
        r = compute("cvd", candles)
        assert r.values
        assert "current" in r.meta
        assert "approximation" in r.meta


# ── Chaikin A/D ──────────────────────────────────────────────────────────


class TestChaikinAD:
    def test_empty_input(self):
        r = compute("chaikin_ad", [])
        assert r.values == []
        assert "reason" in r.meta

    def test_close_at_high_full_accumulation(self):
        # close==high → multiplier = +1 → contribute +volume
        r = compute("chaikin_ad", [_bar(1, 100, 110, 100, 110, 1000)])
        assert r.values == [[1, 1000.0]]

    def test_close_at_low_full_distribution(self):
        r = compute("chaikin_ad", [_bar(1, 100, 110, 100, 100, 1000)])
        assert r.values == [[1, -1000.0]]

    def test_close_at_midpoint_zero_contribution(self):
        # close at exact midpoint → mult 0 → no change
        r = compute("chaikin_ad", [_bar(1, 100, 110, 100, 105, 1000)])
        assert r.values == [[1, 0.0]]

    def test_doji_zero_range_graceful(self):
        # high==low → zero range → zero contribution (not a crash)
        r = compute("chaikin_ad", [_bar(1, 100, 100, 100, 100, 1000)])
        assert r.values == [[1, 0.0]]

    def test_cumulative(self):
        candles = [
            _bar(1, 100, 110, 100, 110, 1000),  # +1000
            _bar(2, 110, 120, 110, 110, 500),   # -500
        ]
        r = compute("chaikin_ad", candles)
        assert [v for _, v in r.values] == [1000.0, 500.0]

    def test_smoke(self):
        candles = [_bar(i, 100, 102, 98, 101, 1000) for i in range(1, 6)]
        r = compute("chaikin_ad", candles)
        assert r.values
        assert "current" in r.meta


# ── Volume Profile ───────────────────────────────────────────────────────


class TestVolumeProfile:
    def test_empty_input(self):
        r = compute("volume_profile", [])
        assert "reason" in r.meta

    def test_flat_price_range_graceful(self):
        # all at same price → no range → meta explains
        candles = [_bar(i, 100, 100, 100, 100, 1000) for i in range(1, 4)]
        r = compute("volume_profile", candles)
        assert "reason" in r.meta

    def test_poc_is_highest_volume_bucket(self):
        # Concentrate volume around one price; POC should land there.
        candles = [
            _bar(1, 100, 101, 99, 100, 100),
            _bar(2, 100, 101, 99, 100, 100),
            _bar(3, 105, 106, 104, 105, 10_000),  # heavy bar at 105
            _bar(4, 110, 111, 109, 110, 100),
        ]
        r = compute("volume_profile", candles, buckets=12)
        poc = r.meta["poc_price"]
        assert 104 <= poc <= 106, f"POC {poc} should be near 105"

    def test_marker_at_poc(self):
        candles = [
            _bar(1, 100, 101, 99, 100, 100),
            _bar(2, 105, 106, 104, 105, 10_000),
            _bar(3, 110, 111, 109, 110, 100),
        ]
        r = compute("volume_profile", candles, buckets=8)
        assert len(r.markers) == 1
        assert r.markers[0]["time"] == 3  # last bar timestamp
        assert "POC" in r.markers[0]["text"]

    def test_buckets_sum_to_total_volume(self):
        candles = [
            _bar(1, 100, 102, 98, 100, 500),
            _bar(2, 101, 103, 99, 102, 700),
            _bar(3, 104, 106, 102, 105, 300),
        ]
        r = compute("volume_profile", candles, buckets=10)
        total = sum(b["volume"] for b in r.meta["buckets"])
        assert abs(total - 1500.0) < 1e-6

    def test_smoke(self):
        candles = [_bar(i, 100 + i, 102 + i, 98 + i, 101 + i, 1000) for i in range(1, 10)]
        r = compute("volume_profile", candles)
        assert r.meta.get("buckets")
        assert r.meta.get("poc_price") is not None


# ── VSA ──────────────────────────────────────────────────────────────────


def _steady(t: int, vol: float = 1000.0, spread: float = 2.0) -> dict[str, Any]:
    # mid-priced bar with controllable volume + spread, up-bar by default
    mid = 100.0
    return _bar(t, mid - 0.2, mid + spread / 2, mid - spread / 2, mid + 0.2, vol)


class TestVSA:
    def test_short_input(self):
        r = compute("vsa", [_steady(i) for i in range(1, 5)])
        assert "reason" in r.meta

    def test_no_markers_when_all_normal(self):
        # 25 steady normal bars → nothing notable, no markers.
        candles = [_steady(i) for i in range(1, 26)]
        r = compute("vsa", candles)
        assert r.markers == []

    def test_absorption_emitted(self):
        # 20 normal bars then a high-volume narrow-spread bar.
        candles = [_steady(i, vol=1000, spread=2.0) for i in range(1, 21)]
        # Bar 21: 3x volume, narrow spread → absorption
        candles.append(_bar(21, 99.9, 100.2, 99.8, 100.0, 3000))
        r = compute("vsa", candles)
        kinds = [m["kind"] for m in r.markers]
        assert "absorption" in kinds

    def test_climactic_up_emitted(self):
        candles = [_steady(i, vol=1000, spread=2.0) for i in range(1, 21)]
        # Bar 21: ultra volume + wide spread + up close → buying climax
        candles.append(_bar(21, 98, 104, 98, 104, 5000))
        r = compute("vsa", candles)
        kinds = [m["kind"] for m in r.markers]
        assert "climax" in kinds

    def test_divergence_required_for_marker(self):
        # A bar with high volume AND wide spread is NOT absorption; it's
        # just a big trending bar. Should not emit absorption marker.
        candles = [_steady(i, vol=1000, spread=2.0) for i in range(1, 21)]
        candles.append(_bar(21, 98, 104, 98, 104, 2000))  # high vol + wide
        r = compute("vsa", candles)
        # high vol + wide is not in any rule (needs 'ultra' for climax)
        # so no absorption/no-supply should fire.
        kinds = [m["kind"] for m in r.markers]
        assert "absorption" not in kinds


# ── Wyckoff Phase ────────────────────────────────────────────────────────


class TestWyckoffPhase:
    def test_short_input(self):
        r = compute("wyckoff_phase", [_bar(i, 100, 101, 99, 100, 1000) for i in range(1, 10)])
        assert "reason" in r.meta

    def test_smoke(self):
        candles = [_bar(i, 100, 101, 99, 100, 1000) for i in range(1, 60)]
        r = compute("wyckoff_phase", candles)
        assert r.values
        assert "current_phase" in r.meta

    def test_markup_detection(self):
        # 50 bars of a tight range near 100, then a breakout with rising
        # OBV (each breakout bar closes above prior, adding volume).
        candles = []
        for i in range(1, 51):
            # Sideways choppy low-volume
            c = 100.0 + (0.2 if i % 2 == 0 else -0.2)
            candles.append(_bar(i, 100, 100.5, 99.5, c, 500))
        # Breakout bars: clear new highs with heavy up-volume
        for j, t in enumerate(range(51, 61)):
            close = 102 + j
            candles.append(_bar(t, close - 0.5, close + 0.5, close - 1, close, 5000))
        r = compute("wyckoff_phase", candles)
        # Somewhere in the breakout window we should see markup.
        phase_codes = [v for _, v in r.values]
        assert 2 in phase_codes, f"expected markup (code 2) in {set(phase_codes)}"

    def test_accumulation_detection(self):
        # First a big drop (establishing the window low), then a tight
        # range at the bottom of that window with rising OBV (up-closes
        # dominate volume).
        candles = []
        # 20 bars drifting down from 120 to 100 (establishes high side of window)
        for i in range(1, 21):
            c = 120 - i
            candles.append(_bar(i, c + 0.3, c + 0.5, c - 0.5, c, 500))
        # 30 bars tight range around 100 with volume skewed to up-closes
        for i in range(21, 51):
            # alternating up/down but up bars get big volume
            if i % 2 == 0:
                candles.append(_bar(i, 99.8, 100.3, 99.5, 100.2, 3000))  # up high vol
            else:
                candles.append(_bar(i, 100.2, 100.4, 99.7, 99.9, 500))   # down low vol
        r = compute("wyckoff_phase", candles)
        phase_codes = [v for _, v in r.values]
        # We should detect accumulation somewhere in the tight-range section.
        assert 1 in phase_codes, f"expected accumulation (code 1) in {set(phase_codes)}"

    def test_phase_codes_in_range(self):
        candles = [_bar(i, 100, 101, 99, 100, 1000) for i in range(1, 60)]
        r = compute("wyckoff_phase", candles)
        for _, code in r.values:
            assert code in (0, 1, 2, 3, 4)


# ── OBV Divergence ───────────────────────────────────────────────────────


class TestOBVDivergence:
    def test_short_input(self):
        r = compute("obv_divergence", [_bar(i, 100, 101, 99, 100, 1000) for i in range(1, 10)])
        assert "reason" in r.meta

    def test_no_divergence_in_healthy_trend(self):
        # Steadily rising price with steadily rising OBV → no divergence.
        candles = []
        for i in range(1, 40):
            c = 100 + i
            # up bars dominate, volume consistent → OBV trends with price
            candles.append(_bar(i, c - 0.5, c + 0.5, c - 1, c, 1000))
        r = compute("obv_divergence", candles)
        assert r.meta["bearish_count"] == 0

    def test_bearish_divergence_emitted(self):
        # 25 bars rising with strong volume → OBV climbs hard.
        candles = []
        prev = 100.0
        for i in range(1, 26):
            c = prev + 1  # up-bar
            candles.append(_bar(i, prev, c + 0.2, prev - 0.2, c, 2000))
            prev = c
        # Then 5 bars making a fresh high but on weak volume with
        # interleaved down-closes so OBV doesn't confirm.
        for i in range(26, 31):
            c = prev + 0.5  # marginal new high
            # Alternate close direction on tiny volume — OBV stagnates.
            if i % 2 == 0:
                candles.append(_bar(i, prev + 0.1, c + 0.1, prev - 0.1, c, 100))
            else:
                # down-close on higher-than-up-bar volume erodes OBV
                candles.append(_bar(i, prev + 0.1, c + 0.1, prev - 0.2, prev - 0.05, 500))
            prev = c
        r = compute("obv_divergence", candles, lookback=20)
        assert r.meta["bearish_count"] >= 1, r.meta

    def test_bullish_divergence_emitted(self):
        # 25 bars falling with strong volume → OBV drops hard.
        candles = []
        prev = 200.0
        for i in range(1, 26):
            c = prev - 1  # down-bar
            candles.append(_bar(i, prev, prev + 0.2, c - 0.2, c, 2000))
            prev = c
        # 5 bars making marginal new lows but OBV stabilizes (up-closes
        # on bigger volume than down-closes).
        for i in range(26, 31):
            c = prev - 0.5  # marginal new low
            if i % 2 == 0:
                # up-close on big volume — lifts OBV despite price low
                candles.append(_bar(i, prev - 0.1, prev, c - 0.1, prev + 0.05, 3000))
            else:
                candles.append(_bar(i, prev - 0.1, prev, c - 0.2, c, 100))
            prev = c
        r = compute("obv_divergence", candles, lookback=20)
        assert r.meta["bullish_count"] >= 1, r.meta

    def test_smoke(self):
        candles = [_bar(i, 100 + (i % 3), 101 + (i % 3), 99, 100 + (i % 3), 1000)
                   for i in range(1, 40)]
        r = compute("obv_divergence", candles)
        assert "bearish_count" in r.meta
        assert "bullish_count" in r.meta
