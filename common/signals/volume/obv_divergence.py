"""OBV divergence detector — bullish + bearish.

Scans for bars where price prints an N-bar extreme but OBV does not
confirm: price new high + OBV below its N-bar high = bearish
divergence (distribution); price new low + OBV above its N-bar low =
bullish divergence (accumulation). Emits markers at confirmed
divergences only.

Reuses the registered `obv` signal for the OBV series to avoid drift.
"""
from __future__ import annotations

from typing import Any

from common.signals.base import Candle, ChartSpec, Signal, SignalCard, SignalResult
from common.signals.registry import compute as registry_compute
from common.signals.registry import register


def _to_float(x: Any) -> float:
    try:
        return float(x)
    except (TypeError, ValueError):
        return 0.0


@register
class OBVDivergence(Signal):
    card = SignalCard(
        name="OBV Divergence",
        slug="obv_divergence",
        category="volume",
        what=(
            "Marker-only overlay that flags confirmed price/OBV "
            "divergences over a rolling N-bar window. A bearish "
            "divergence is emitted when the current bar's close is "
            "the highest in the last N bars but OBV is below its "
            "own N-bar high — distribution into strength. Bullish is "
            "the mirror: new N-bar price low with OBV above its N-bar "
            "low — accumulation on the dip."
        ),
        basis=(
            "Classical divergence analysis as described by John J. "
            "Murphy ('Technical Analysis of the Financial Markets') "
            "and popularized in countless OBV write-ups since "
            "Granville. The rolling-extreme detection shape is the "
            "standard mechanical form of the rule."
        ),
        how_to_read=(
            "• Bearish marker at a new price high = trend exhaustion "
            "risk; volume is not following the rally. Tighten longs, "
            "consider partial profit.\n"
            "• Bullish marker at a new price low = selling without "
            "commitment; candidate for a mean-reversion long once "
            "price structure confirms.\n"
            "• Single markers are information, not signals — wait "
            "for price-structure confirmation (break of the most "
            "recent swing).\n"
            "• Clusters of same-direction markers in a short window "
            "are stronger than an isolated one."
        ),
        failure_modes=(
            "• Strong trends can print multiple bearish divergences "
            "before the actual top (or vice versa) — divergence is "
            "a warning, not a timer.\n"
            "• Too-short N (e.g. 5) produces noisy, meaningless "
            "markers; too-long N (e.g. 200) misses anything but "
            "major swings. Default 20 is a compromise.\n"
            "• Shares OBV's failure modes: thin books, wash trading, "
            "gap candles all degrade the signal."
        ),
        inputs="close, volume",
        params={"lookback": 20},
    )
    chart_spec = ChartSpec(
        placement="overlay",
        series_type="markers",
        color="primary",
        axis="price",
        series_name="OBV Divergence",
        priority=5,
    )

    def compute(self, candles: list[Candle], **params: Any) -> SignalResult:
        result = self.new_result()
        n = int(params.get("lookback", self.card.params["lookback"]))
        if n < 2:
            n = 2
        if len(candles) < n + 1:
            result.meta = {"reason": f"need ≥{n+1} candles"}
            return result

        obv_res = registry_compute("obv", candles)
        obv_vals = [v for _, v in obv_res.values]
        if len(obv_vals) != len(candles):
            # OBV seeds at index 0 with zero and returns one value per candle.
            # If that invariant breaks we bail rather than misalign indices.
            result.meta = {"reason": "OBV series length mismatch"}
            return result

        closes = [_to_float(c["c"]) for c in candles]
        times = [int(c["t"]) for c in candles]

        bullish = 0
        bearish = 0
        for i in range(n, len(candles)):
            window_closes = closes[i - n:i + 1]
            window_obv = obv_vals[i - n:i + 1]
            c_now = closes[i]
            o_now = obv_vals[i]

            is_price_high = c_now >= max(window_closes)
            is_price_low = c_now <= min(window_closes)
            obv_max = max(window_obv)
            obv_min = min(window_obv)

            if is_price_high and o_now < obv_max:
                # Bearish divergence: price confirms, OBV doesn't.
                result.markers.append({
                    "time": times[i],
                    "position": "above",
                    "color": "negative",
                    "shape": "arrowDown",
                    "text": "Bearish div (OBV)",
                    "price": round(c_now, 6),
                })
                bearish += 1
            elif is_price_low and o_now > obv_min:
                result.markers.append({
                    "time": times[i],
                    "position": "below",
                    "color": "positive",
                    "shape": "arrowUp",
                    "text": "Bullish div (OBV)",
                    "price": round(c_now, 6),
                })
                bullish += 1

        result.meta = {
            "lookback": n,
            "bullish_count": bullish,
            "bearish_count": bearish,
            "total_markers": bullish + bearish,
            "bar_count": len(candles),
        }
        return result
