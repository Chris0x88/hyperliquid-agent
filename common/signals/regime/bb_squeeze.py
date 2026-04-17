"""Bollinger Band Squeeze — volatility compression detector.

Measures how compressed the Bollinger Bands are relative to their own
recent history. Tight bands precede expansion: "the calmest hour is
before the storm."

Classic TTM Squeeze (John Carter) uses BB-inside-Keltner as the squeeze
condition. This implementation uses the simpler and more legible BB
width percentile approach — current BB width ranked against the last N
bars of BB widths. Bottom 20% = squeeze. Rising out of the bottom = release.
"""
from __future__ import annotations

import math
from typing import Any

from common.signals.base import Candle, ChartSpec, Signal, SignalCard
from common.signals.registry import register


def _to_float(x: Any) -> float:
    try:
        return float(x)
    except (TypeError, ValueError):
        return 0.0


def _mean(xs: list[float]) -> float:
    return sum(xs) / len(xs) if xs else 0.0


def _std(xs: list[float]) -> float:
    if len(xs) < 2:
        return 0.0
    m = _mean(xs)
    var = sum((x - m) ** 2 for x in xs) / len(xs)  # population stdev for BB
    return math.sqrt(var)


@register
class BBSqueeze(Signal):
    card = SignalCard(
        name="Bollinger Band Squeeze",
        slug="bb_squeeze",
        category="regime",
        what=(
            "Rolling Bollinger Band width (upper - lower)/middle, rendered "
            "as a histogram. Markers fire when width compresses into the "
            "bottom 20% of its own recent distribution (squeeze onset) and "
            "when width crosses back above that threshold (release)."
        ),
        basis=(
            "Bollinger Bands: John Bollinger, 1980s. Squeeze concept "
            "popularized by John Carter's 'TTM Squeeze' (2007, "
            "'Mastering the Trade'). This variant uses BB-width percentile "
            "rather than BB-inside-Keltner for simpler interpretation."
        ),
        how_to_read=(
            "• Histogram at/near zero → bands are tight, volatility "
            "compressed. A breakout move is loading.\n"
            "• Squeeze onset marker (↓ below bar) → width just entered "
            "the bottom 20%. The market is coiling.\n"
            "• Squeeze release marker (↑ above bar) → width expanded out "
            "of the squeeze zone. Direction of the release often persists "
            "for 5-20 bars.\n"
            "• Pair with ADX: squeeze releasing INTO a rising ADX = "
            "highest-probability trend breakout.\n"
            "• Direction of the break is NOT in this signal — look at "
            "price relative to the middle band at release."
        ),
        failure_modes=(
            "• False starts: squeezes can release and immediately re-enter "
            "squeeze (double coil). Not every release leads to trend.\n"
            "• Low-liquidity hours (weekend crypto, overnight equities) "
            "artificially compress width — not a real signal.\n"
            "• On high timeframes (weekly+), a squeeze can last months; "
            "don't front-run the release.\n"
            "• News-driven gap opens can skip the squeeze release entirely."
        ),
        inputs="close",
        params={"bb_period": 20, "bb_stdev": 2.0, "rank_window": 100, "squeeze_pct": 0.20},
    )
    chart_spec = ChartSpec(
        placement="subpane",
        series_type="histogram",
        color="warning",
        axis="raw",
        series_name="BB Width",
        priority=0,
    )

    def compute(self, candles: list[Candle], **params: Any) -> Any:
        bb_period = int(params.get("bb_period", 20))
        bb_stdev = float(params.get("bb_stdev", 2.0))
        rank_window = int(params.get("rank_window", 100))
        squeeze_pct = float(params.get("squeeze_pct", 0.20))

        result = self.new_result()
        min_bars = bb_period + rank_window
        if len(candles) < min_bars:
            result.meta = {"reason": f"need ≥{min_bars} bars"}
            return result

        closes = [_to_float(c["c"]) for c in candles]
        timestamps = [int(c["t"]) for c in candles]

        # BB width per bar (undefined for first bb_period-1 bars)
        widths: list[float | None] = [None] * (bb_period - 1)
        for i in range(bb_period - 1, len(closes)):
            window = closes[i - bb_period + 1 : i + 1]
            m = _mean(window)
            s = _std(window)
            if m > 0:
                width = (2.0 * bb_stdev * s) / m
            else:
                width = 0.0
            widths.append(width)

        # Percentile rank of current width vs previous `rank_window` widths
        # (use strictly-previous to avoid self-inclusion bias at extremes).
        in_squeeze_prev = False
        for i in range(bb_period - 1 + rank_window, len(widths)):
            current = widths[i]
            if current is None:
                continue
            # strictly previous window
            past = [w for w in widths[i - rank_window : i] if w is not None]
            if len(past) < rank_window // 2:
                continue
            rank = sum(1 for w in past if w < current) / len(past)
            result.values.append([timestamps[i], round(current, 6)])

            in_squeeze = rank <= squeeze_pct
            # Edge-triggered markers: onset and release only
            if in_squeeze and not in_squeeze_prev:
                result.markers.append({
                    "time": timestamps[i],
                    "position": "belowBar",
                    "color": "warning",
                    "shape": "arrowDown",
                    "text": "squeeze on",
                })
            elif not in_squeeze and in_squeeze_prev:
                result.markers.append({
                    "time": timestamps[i],
                    "position": "aboveBar",
                    "color": "success",
                    "shape": "arrowUp",
                    "text": "squeeze off",
                })
            in_squeeze_prev = in_squeeze

        if result.values:
            result.meta = {
                "current_width": result.values[-1][1],
                "in_squeeze": in_squeeze_prev,
                "squeeze_events": len(result.markers),
            }
        return result
