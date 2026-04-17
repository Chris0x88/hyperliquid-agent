"""Cumulative Volume Delta (CVD) — bar-approximated.

True CVD requires tick-level trade data to classify each trade as a buy
(aggressor hits ask) or sell (aggressor hits bid). At candle-level we
don't have that, so we approximate using bar direction: an up-bar's
volume is counted as buy-side, a down-bar's as sell-side, a doji splits
50/50. The running sum of signed volume is the CVD proxy.

Note: this is a candle approximation. On exchanges with published
trade tapes the proper CVD will differ — sometimes materially during
absorption bars where the tape goes one way and the close the other.
Use with that caveat.
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
class CVD(Signal):
    card = SignalCard(
        name="Cumulative Volume Delta (candle-approx)",
        slug="cvd",
        category="volume",
        what=(
            "Running cumulative sum of signed volume, where each bar's "
            "volume is signed by the bar's direction: up-bar (close>open) "
            "counts as buy-side (+volume), down-bar (close<open) as "
            "sell-side (-volume), doji (close==open) splits 50/50 so "
            "contributes zero net. Approximates the true trade-tape CVD "
            "which requires tick data."
        ),
        basis=(
            "CVD as a concept is attributed to order-flow traders in "
            "the mid-2000s (TradingView, Sierra Chart, ATAS docs). The "
            "candle-approximation form used here is the standard "
            "fallback when tick data is unavailable — see Volumetrica's "
            "notes and the TradingView 'Cumulative Volume Delta' study."
        ),
        how_to_read=(
            "• CVD trending up with price → healthy buying, trend OK.\n"
            "• Price makes new high, CVD does NOT → absorption / bearish "
            "divergence. Aggressive sellers are soaking up the buying.\n"
            "• Price makes new low, CVD does NOT → accumulation / "
            "bullish divergence. Buyers are soaking up the selling.\n"
            "• CVD flatlining in a range → balance; wait for break.\n"
            "• Remember: this is candle-approximated — on heavy "
            "absorption bars (wide-spread close near the opposite end) "
            "the true tick-tape CVD can differ from this proxy."
        ),
        failure_modes=(
            "• Candle approximation — tick-true CVD can diverge, "
            "especially on absorption/reversal bars.\n"
            "• Wash trades and iceberg orders are invisible here.\n"
            "• Low-volume markets produce noisy CVD.\n"
            "• Use alongside OBV — they agree most of the time, and "
            "disagreement is itself a signal worth investigating."
        ),
        inputs="open, close, volume",
        params={},
    )
    chart_spec = ChartSpec(
        placement="subpane",
        series_type="line",
        color="tertiary",
        axis="raw",
        series_name="CVD",
        priority=0,
    )

    def compute(self, candles: list[Candle], **_: Any) -> SignalResult:
        result = self.new_result()
        if not candles:
            result.meta = {"reason": "no candles provided"}
            return result

        cvd = 0.0
        for c in candles:
            o = _to_float(c["o"])
            close = _to_float(c["c"])
            vol = _to_float(c["v"])
            if close > o:
                cvd += vol
            elif close < o:
                cvd -= vol
            # doji: net 0 contribution (the 50/50 split cancels)
            result.values.append([int(c["t"]), round(cvd, 4)])

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
            "approximation": "candle-level (no tick data)",
        }
        return result
