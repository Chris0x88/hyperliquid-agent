"""On-Balance Volume (OBV) — Joseph Granville, 1963.

Cumulative sum of volume, signed by close direction. Classic accumulation
/ distribution detector. Divergences between OBV and price often lead
price by 1-3 bars because volume reveals institutional intent before
price does.

This is the reference implementation for the signals framework — it's the
shape every other signal follows.
"""
from __future__ import annotations

from typing import Any

from common.signals.base import Candle, ChartSpec, Signal, SignalCard, SignalResult
from common.signals.registry import register


def _to_float(x: Any) -> float:
    """Coerce candle values (which may be strings from SQLite) to float."""
    try:
        return float(x)
    except (TypeError, ValueError):
        return 0.0


@register
class OBV(Signal):
    card = SignalCard(
        name="On-Balance Volume (OBV)",
        slug="obv",
        category="volume",
        what=(
            "Cumulative sum of volume, where each bar's volume is added "
            "when close > previous close, subtracted when close < previous "
            "close, and ignored when close is unchanged. Measures net buying "
            "vs selling pressure over time."
        ),
        basis=(
            "Joseph Granville, 'New Key to Stock Market Profits' (1963). One "
            "of the oldest volume indicators still in active use. Widely "
            "documented in Murphy, Pring, and Schwager."
        ),
        how_to_read=(
            "• OBV trending UP with price → healthy trend, volume confirms.\n"
            "• OBV flat/falling while price rises → bearish divergence, "
            "distribution likely (smart money selling into strength).\n"
            "• OBV rising while price flat/falling → bullish divergence, "
            "accumulation likely (smart money buying the dip).\n"
            "• OBV breakout PRECEDING a price breakout is a classic long/short "
            "setup — volume leads price by 1-3 bars on average.\n"
            "• Look for OBV to break its own trendlines before trading."
        ),
        failure_modes=(
            "• Low-volume markets (thin alts, weekends) produce noisy OBV.\n"
            "• Spot vs perp OBV diverge structurally — know which you're "
            "looking at.\n"
            "• Wash trading on some venues inflates volume and poisons OBV.\n"
            "• Gap candles (news shocks) create artificial OBV jumps — "
            "discount signals across known gaps."
        ),
        inputs="close, volume",
        params={},  # OBV has no parameters — it's a pure cumulative series
    )
    chart_spec = ChartSpec(
        placement="subpane",
        series_type="line",
        color="tertiary",  # #87CAE6 — theme token resolved by dashboard
        axis="raw",
        series_name="OBV",
        priority=0,
    )

    def compute(self, candles: list[Candle], **_: Any) -> SignalResult:
        result = self.new_result()
        if len(candles) < 2:
            result.meta = {"reason": "need ≥2 candles for OBV"}
            return result

        obv = 0.0
        prev_close = _to_float(candles[0]["c"])
        # First bar seeds the series at zero (no prior close to diff against).
        result.values.append([int(candles[0]["t"]), 0.0])

        for c in candles[1:]:
            close = _to_float(c["c"])
            vol = _to_float(c["v"])
            if close > prev_close:
                obv += vol
            elif close < prev_close:
                obv -= vol
            # close == prev_close → OBV unchanged
            result.values.append([int(c["t"]), round(obv, 4)])
            prev_close = close

        # Meta: current value + simple trend label from last N bars
        n = min(10, len(result.values))
        if n >= 2:
            recent_first = result.values[-n][1]
            recent_last = result.values[-1][1]
            delta = recent_last - recent_first
            if delta > 0:
                trend = "rising"
            elif delta < 0:
                trend = "falling"
            else:
                trend = "flat"
        else:
            trend = "unknown"

        result.meta = {
            "current": result.values[-1][1] if result.values else 0.0,
            "trend_last_10": trend,
            "bar_count": len(result.values),
        }
        return result
