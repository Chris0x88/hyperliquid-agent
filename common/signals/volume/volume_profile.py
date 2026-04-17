"""Horizontal volume profile — price-level buckets of total volume.

Partitions the full price range covered by the candle window into N
equal-height buckets, assigns each candle's volume to the bucket
containing its typical price ((H+L+C)/3), then reports per-bucket
totals plus the Point of Control (POC = the bucket with the highest
total volume).

This is NOT a time series, so `values` stays empty. The buckets live
in `meta` and a single marker is emitted at the POC price on the last
bar's timestamp so the chart can render a horizontal reference line.
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
class VolumeProfile(Signal):
    card = SignalCard(
        name="Volume Profile",
        slug="volume_profile",
        category="volume",
        what=(
            "Horizontal histogram: for each price-level bucket in the "
            "candle window, the total volume transacted. The bucket "
            "with the highest volume is the Point of Control (POC) — "
            "the price that saw the most activity. Typical price "
            "(H+L+C)/3 is used to assign each candle's volume to a "
            "bucket; a more faithful implementation would distribute "
            "each bar's volume across its full range, but the "
            "single-bucket approximation is what's shipped here."
        ),
        basis=(
            "Market Profile concepts by Peter Steidlmayer (CBOT, 1980s) "
            "and the fixed-range volume profile as popularized by "
            "Sierra Chart, ATAS, and TradingView. POC terminology is "
            "Steidlmayer's."
        ),
        how_to_read=(
            "• POC is where the market found acceptance — expect it "
            "to act as magnet/support when price revisits it.\n"
            "• Price far above POC with thinning volume = potential "
            "reversion zone.\n"
            "• Low-volume nodes (gaps in the profile) tend to travel "
            "through quickly once broken — don't expect them to hold.\n"
            "• High-volume nodes outside the POC are secondary "
            "support/resistance.\n"
            "• Compare POC to current price: above POC and rising = "
            "market seeking higher value; below and falling = seeking "
            "lower value."
        ),
        failure_modes=(
            "• Single-bucket assignment (this implementation) is "
            "coarser than a proper range-distributed profile — use it "
            "as directional guidance, not exact levels.\n"
            "• Very small windows produce noisy profiles with a "
            "meaningless POC.\n"
            "• News gaps leave low-volume nodes that revisit fast but "
            "that's still tradable info.\n"
            "• Bucket count parameter matters — too few and POC is "
            "too wide to use, too many and every bar is its own peak."
        ),
        inputs="high, low, close, volume",
        params={"buckets": 24},
    )
    chart_spec = ChartSpec(
        placement="subpane",
        series_type="markers",
        color="primary",
        axis="price",
        series_name="Volume Profile POC",
        priority=0,
    )

    def compute(self, candles: list[Candle], **params: Any) -> SignalResult:
        result = self.new_result()
        if not candles:
            result.meta = {"reason": "no candles provided"}
            return result

        buckets = int(params.get("buckets", self.card.params["buckets"]))
        if buckets < 2:
            buckets = 2

        highs = [_to_float(c["h"]) for c in candles]
        lows = [_to_float(c["l"]) for c in candles]
        hi = max(highs)
        lo = min(lows)
        if hi <= lo:
            result.meta = {"reason": "no price range in window"}
            return result

        width = (hi - lo) / buckets
        totals = [0.0] * buckets
        for c in candles:
            h = _to_float(c["h"])
            l = _to_float(c["l"])
            close = _to_float(c["c"])
            vol = _to_float(c["v"])
            tp = (h + l + close) / 3.0
            idx = int((tp - lo) / width) if width > 0 else 0
            if idx >= buckets:
                idx = buckets - 1
            if idx < 0:
                idx = 0
            totals[idx] += vol

        bucket_list = []
        for i, v in enumerate(totals):
            bucket_lo = lo + i * width
            bucket_hi = bucket_lo + width
            bucket_list.append({
                "price_low": round(bucket_lo, 6),
                "price_high": round(bucket_hi, 6),
                "volume": round(v, 4),
            })

        poc_idx = max(range(buckets), key=lambda i: totals[i])
        poc_price = lo + (poc_idx + 0.5) * width
        poc_volume = totals[poc_idx]

        # Marker at POC on the final bar's timestamp.
        last_t = int(candles[-1]["t"])
        result.markers = [{
            "time": last_t,
            "position": "inBar",
            "color": "primary",
            "shape": "circle",
            "text": f"POC {round(poc_price, 4)}",
            "price": round(poc_price, 6),
        }]

        result.meta = {
            "buckets": bucket_list,
            "poc_price": round(poc_price, 6),
            "poc_volume": round(poc_volume, 4),
            "poc_bucket_index": poc_idx,
            "price_range": [round(lo, 6), round(hi, 6)],
            "bar_count": len(candles),
        }
        return result
