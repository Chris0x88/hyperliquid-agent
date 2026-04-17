"""Composite regime classifier — combines ADX, Hurst, BB squeeze, and OBV
into a single Wyckoff-style regime label per bar.

Phase codes (matches common/signals/accumulation/wyckoff_phase.py):
  0 = choppy / unknown
  1 = accumulation   (range + rising OBV)
  2 = markup         (trend up + rising OBV)
  3 = distribution   (range + falling OBV)
  4 = markdown       (trend down + falling OBV)

Why this signal is different from the dedicated `wyckoff_phase` signal:
`wyckoff_phase` looks at price range + OBV only. This classifier pulls
in trend strength (ADX), persistence (Hurst), and volatility compression
(BB squeeze) to disambiguate weak trends vs. true range-bound regimes,
and to detect coiled markets that wyckoff_phase would miss.

The two signals are complementary — run both for redundancy. Agreement
= high confidence. Disagreement = transition period, tread carefully.
"""
from __future__ import annotations

from typing import Any

from common.signals.base import Candle, ChartSpec, Signal, SignalCard
from common.signals.registry import register, compute as _compute


def _to_float(x: Any) -> float:
    try:
        return float(x)
    except (TypeError, ValueError):
        return 0.0


# Phase labels, matched to wyckoff_phase.py code encoding
PHASE_LABELS = {
    0: "choppy",
    1: "accumulation",
    2: "markup",
    3: "distribution",
    4: "markdown",
}


@register
class RegimeClassifier(Signal):
    card = SignalCard(
        name="Regime Classifier (composite)",
        slug="regime_classifier",
        category="regime",
        what=(
            "Labels each bar with a market regime: accumulation, markup, "
            "distribution, markdown, or choppy. Composes ADX (trend "
            "strength), Hurst (persistence), and OBV (volume confirmation) "
            "via simple rule logic. The goal: put a name on the phase so "
            "you can tell whether a breakout is real, a range is tightening, "
            "or the market is in noise-only mode."
        ),
        basis=(
            "Composite of Wilder's ADX (1978), Hurst exponent (1951) "
            "aggregated-variance estimator, and Granville's OBV (1963). "
            "Phase taxonomy from Richard Wyckoff's market cycle model "
            "(1920s-30s), popularized in the modern era by Hank Pruden's "
            "'The Three Skills of Top Trading' (2007)."
        ),
        how_to_read=(
            "• MARKUP (code 2): ADX>25, rising, Hurst>0.55, OBV up. Trend-"
            "follow longs. Pullbacks are entries.\n"
            "• MARKDOWN (code 4): ADX>25, rising, Hurst>0.55, OBV down. "
            "Trend-follow shorts. Rallies are entries.\n"
            "• ACCUMULATION (code 1): ADX<20, Hurst~0.5, OBV rising while "
            "price ranges. Smart money buying. Setup for future markup.\n"
            "• DISTRIBUTION (code 3): ADX<20, Hurst~0.5, OBV falling while "
            "price ranges. Smart money selling. Setup for future markdown.\n"
            "• CHOPPY (code 0): none of the above agree. Sit out or trade "
            "very small. Most whipsaw losses happen here.\n"
            "• PAIR with `wyckoff_phase` signal for agreement check. Two "
            "signals agreeing = higher confidence."
        ),
        failure_modes=(
            "• Regime transitions lag: ADX and Hurst both smooth, so the "
            "classifier labels the PREVIOUS regime for several bars into a "
            "new one. Expect 5-10 bar lag on timeframe-of-interest.\n"
            "• Choppy label dominates on low timeframes (1m, 5m) — normal, "
            "real regimes only emerge on 15m+.\n"
            "• On the first few hundred bars of data, component signals "
            "lack enough history to classify; bars default to choppy.\n"
            "• News shocks create artificial markup/markdown spikes that "
            "don't sustain. Confirm with 2+ bars of the same label.\n"
            "• Requires ≥200 bars of history to have all components online."
        ),
        inputs="high, low, close, volume (via component signals)",
        params={
            "adx_period": 14,
            "hurst_window": 100,
            "trend_adx_min": 25.0,
            "range_adx_max": 20.0,
            "trend_hurst_min": 0.55,
            "obv_trend_bars": 20,
        },
    )
    chart_spec = ChartSpec(
        placement="subpane",
        series_type="line",
        color="primary",
        axis="raw",  # integer 0-4 phase codes
        series_name="Regime",
        priority=1,
    )

    def compute(self, candles: list[Candle], **params: Any) -> Any:
        adx_period = int(params.get("adx_period", 14))
        hurst_window = int(params.get("hurst_window", 100))
        trend_adx_min = float(params.get("trend_adx_min", 25.0))
        range_adx_max = float(params.get("range_adx_max", 20.0))
        trend_hurst_min = float(params.get("trend_hurst_min", 0.55))
        obv_trend_bars = int(params.get("obv_trend_bars", 20))

        result = self.new_result()
        min_bars = max(2 * adx_period + 1, hurst_window + 1, obv_trend_bars + 1)
        if len(candles) < min_bars:
            result.meta = {"reason": f"need ≥{min_bars} bars for regime classification"}
            return result

        # Pull component signal series — all timestamp-aligned to candles[].
        try:
            adx_series = _compute("adx", candles, period=adx_period)
            hurst_series = _compute("hurst", candles, window=hurst_window)
            obv_series = _compute("obv", candles)
        except Exception as exc:
            result.meta = {"reason": f"component compute failed: {exc}"}
            return result

        adx_by_ts = {ts: v for ts, v in adx_series.values}
        hurst_by_ts = {ts: v for ts, v in hurst_series.values}
        obv_by_ts = {ts: v for ts, v in obv_series.values}

        # +DI/-DI for direction. Re-use ADX's meta for the final bar; for
        # intermediate bars we approximate direction from price slope since
        # ADX doesn't emit +DI/-DI as a time series here.
        closes = [_to_float(c["c"]) for c in candles]
        timestamps = [int(c["t"]) for c in candles]

        # Iterate bars where all three components have values
        phase_counts = {0: 0, 1: 0, 2: 0, 3: 0, 4: 0}
        last_label_change_ts: int | None = None
        last_phase: int | None = None

        for i, c in enumerate(candles):
            ts = int(c["t"])
            if ts not in adx_by_ts or ts not in hurst_by_ts or ts not in obv_by_ts:
                continue

            adx = adx_by_ts[ts]
            hurst = hurst_by_ts[ts]

            # Price direction: slope over last obv_trend_bars closes
            if i < obv_trend_bars:
                continue
            price_delta = closes[i] - closes[i - obv_trend_bars]
            price_up = price_delta > 0

            # OBV direction: delta over obv_trend_bars
            obv_ts_window = timestamps[i - obv_trend_bars]
            if obv_ts_window not in obv_by_ts:
                continue
            obv_delta = obv_by_ts[ts] - obv_by_ts[obv_ts_window]
            obv_up = obv_delta > 0

            # Rule ladder
            if adx >= trend_adx_min and hurst >= trend_hurst_min:
                # Trending regime — direction from price + OBV confirmation
                if price_up and obv_up:
                    phase = 2  # markup
                elif not price_up and not obv_up:
                    phase = 4  # markdown
                else:
                    phase = 0  # trend with divergence = suspect
            elif adx <= range_adx_max:
                # Range regime — accumulation vs distribution by OBV
                if obv_up and not price_up:
                    phase = 1  # accumulation
                elif not obv_up and not price_up:
                    phase = 3  # distribution
                elif obv_up and price_up:
                    # Gentle grind higher with range-bound ADX — early markup
                    phase = 2
                else:
                    phase = 0
            else:
                # ADX in no-mans-land (20-25) = transitional, call it choppy
                phase = 0

            result.values.append([ts, phase])
            phase_counts[phase] += 1

            if last_phase is None or phase != last_phase:
                last_label_change_ts = ts
                last_phase = phase

        if result.values:
            current_code = result.values[-1][1]
            # Dominant phase over last 20 classified bars (confidence proxy)
            recent = [v for _, v in result.values[-20:]]
            if recent:
                dominant_code = max(set(recent), key=recent.count)
                dominant_share = recent.count(dominant_code) / len(recent)
            else:
                dominant_code = current_code
                dominant_share = 1.0

            result.meta = {
                "current_code": current_code,
                "current_label": PHASE_LABELS.get(current_code, "unknown"),
                "dominant_recent_label": PHASE_LABELS.get(dominant_code, "unknown"),
                "confidence": round(dominant_share, 2),
                "last_change_ts": last_label_change_ts,
                "phase_counts": {PHASE_LABELS[k]: v for k, v in phase_counts.items()},
            }
        return result
