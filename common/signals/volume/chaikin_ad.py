"""Chaikin Accumulation/Distribution Line — Marc Chaikin, 1970s.

For each bar, the 'money flow multiplier' is ((C - L) - (H - C)) / (H - L),
bounded in [-1, +1]. Multiply by volume to get money flow volume, then
cumulate. Close near high on heavy volume → accumulation. Close near low
on heavy volume → distribution. Unlike OBV which only looks at close vs
prev close, Chaikin A/D examines where in the bar's range the close
landed — catching stealth accumulation that OBV misses.
"""
from __future__ import annotations

from typing import Any

from common.signals.base import Candle, ChartSpec, Signal, SignalCard, SignalResult
from common.signals.registry import register


def _to_float(x: Any) -> float:
    try:
        return float(x)
    except (TypeError, ValueError):
        return 0.0


@register
class ChaikinAD(Signal):
    card = SignalCard(
        name="Chaikin Accumulation/Distribution Line",
        slug="chaikin_ad",
        category="volume",
        what=(
            "Cumulative money flow volume, where each bar contributes "
            "((close - low) - (high - close)) / (high - low) * volume. "
            "The multiplier is +1 when close is at the high (pure "
            "accumulation), -1 at the low (pure distribution), and 0 at "
            "the midpoint. Weights every bar by the close's position "
            "within the bar range."
        ),
        basis=(
            "Marc Chaikin, early 1970s. Widely documented in Murphy's "
            "'Technical Analysis of the Financial Markets' and the "
            "original Chaikin Analytics materials. Closely related to, "
            "but structurally different from, OBV."
        ),
        how_to_read=(
            "• A/D rising while price rises → healthy trend.\n"
            "• Price making new highs, A/D flat/falling → distribution "
            "into the rally (closes drifting toward bar lows).\n"
            "• Price making new lows, A/D flat/rising → accumulation "
            "on the dip (closes drifting toward bar highs).\n"
            "• Compare to OBV: agreement = strong read, divergence "
            "means one of them is missing something — usually A/D "
            "catches intra-bar stealth flow that OBV's close-to-close "
            "view misses.\n"
            "• Absolute level is arbitrary (depends on start time); "
            "slope and divergences are what matter."
        ),
        failure_modes=(
            "• Doji / inside bars where high==low produce a zero "
            "denominator — handled by setting the bar's contribution "
            "to zero, but clusters of them mute the signal.\n"
            "• Gap candles distort the multiplier (close can be far "
            "from the prior close yet near the bar's own high/low).\n"
            "• Like OBV, poisoned by wash trading on thin venues.\n"
            "• Needs full OHLC — useless on tick charts or data where "
            "only close is reliable."
        ),
        inputs="high, low, close, volume",
        params={},
    )
    chart_spec = ChartSpec(
        placement="subpane",
        series_type="line",
        color="primary",
        axis="raw",
        series_name="Chaikin A/D",
        priority=0,
    )

    def compute(self, candles: list[Candle], **_: Any) -> SignalResult:
        result = self.new_result()
        if not candles:
            result.meta = {"reason": "no candles provided"}
            return result

        ad = 0.0
        for c in candles:
            h = _to_float(c["h"])
            l = _to_float(c["l"])
            close = _to_float(c["c"])
            vol = _to_float(c["v"])
            rng = h - l
            if rng > 0:
                mult = ((close - l) - (h - close)) / rng
                ad += mult * vol
            # else: doji / inside bar → zero contribution
            result.values.append([int(c["t"]), round(ad, 4)])

        n = min(10, len(result.values))
        if n >= 2:
            delta = result.values[-1][1] - result.values[-n][1]
            trend = "rising" if delta > 0 else "falling" if delta < 0 else "flat"
        else:
            trend = "unknown"

        result.meta = {
            "current": result.values[-1][1],
            "trend_last_10": trend,
            "bar_count": len(result.values),
        }
        return result
