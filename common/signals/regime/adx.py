"""Average Directional Index (ADX) — J. Welles Wilder, 1978.

Measures TREND STRENGTH regardless of direction. Separately, +DI/-DI
indicate the direction.

This is the cleanest way to distinguish "trending market" from "ranging
market" — a key input for the composite regime classifier.
"""
from __future__ import annotations

from typing import Any

from common.signals.base import Candle, ChartSpec, Signal, SignalCard
from common.signals.registry import register


def _to_float(x: Any) -> float:
    try:
        return float(x)
    except (TypeError, ValueError):
        return 0.0


def _wilder_smooth(values: list[float], period: int) -> list[float]:
    """Wilder's smoothing: EMA variant with alpha = 1/period.

    First value = simple sum of first `period` inputs.
    Subsequent: prev - (prev / period) + current.
    Returns a list offset by `period` bars (first period-1 are None-equivalent,
    skipped in the output).
    """
    if len(values) < period:
        return []
    smoothed: list[float] = []
    first = sum(values[:period])
    smoothed.append(first)
    for v in values[period:]:
        smoothed.append(smoothed[-1] - smoothed[-1] / period + v)
    return smoothed


@register
class ADX(Signal):
    card = SignalCard(
        name="Average Directional Index (ADX)",
        slug="adx",
        category="regime",
        what=(
            "Measures trend strength on a 0-100 scale, independent of "
            "direction. Computed from smoothed +DM/-DM (directional movement) "
            "and True Range over a rolling period (Wilder default: 14 bars)."
        ),
        basis=(
            "J. Welles Wilder Jr., 'New Concepts in Technical Trading Systems' "
            "(1978). Also defined True Range, RSI, and Parabolic SAR in the "
            "same book — still the technical-analysis canon."
        ),
        how_to_read=(
            "• ADX < 20 → no trend, range/chop. Mean-reversion strategies tend "
            "to work here; breakout trades tend to fail.\n"
            "• ADX 20-25 → trend emerging. Watch for confirmation.\n"
            "• ADX 25-50 → healthy trend. Follow-through trades work best.\n"
            "• ADX > 50 → extreme trend, often near exhaustion. Don't chase.\n"
            "• RISING ADX (any level) = trend strengthening. FALLING ADX = "
            "trend weakening, even if still high.\n"
            "• ADX says nothing about direction — pair with +DI/-DI or price "
            "action for long/short bias."
        ),
        failure_modes=(
            "• Slow to react: ADX lags price by design (double-smoothed).\n"
            "• Sideways post-breakout can still show high ADX from the prior "
            "trend — confirm with price structure.\n"
            "• Tunable period (14 default) changes all thresholds — don't "
            "apply the 20/25/50 heuristics if you've changed the period.\n"
            "• Useless on very short timeframes (1m) due to noise."
        ),
        inputs="high, low, close",
        params={"period": 14},
    )
    chart_spec = ChartSpec(
        placement="subpane",
        series_type="line",
        color="primary",
        axis="percent",
        series_name="ADX",
        priority=0,
    )

    def compute(self, candles: list[Candle], **params: Any) -> Any:
        period = int(params.get("period", 14))
        result = self.new_result()

        # Need at least 2*period bars: one period to seed TR/DM smoothing,
        # another to seed ADX itself from DX.
        if len(candles) < 2 * period + 1:
            result.meta = {"reason": f"need ≥{2 * period + 1} bars for ADX(period={period})"}
            return result

        highs = [_to_float(c["h"]) for c in candles]
        lows = [_to_float(c["l"]) for c in candles]
        closes = [_to_float(c["c"]) for c in candles]
        timestamps = [int(c["t"]) for c in candles]

        # True Range, +DM, -DM per bar (starting from index 1)
        tr: list[float] = []
        plus_dm: list[float] = []
        minus_dm: list[float] = []
        for i in range(1, len(candles)):
            tr_i = max(
                highs[i] - lows[i],
                abs(highs[i] - closes[i - 1]),
                abs(lows[i] - closes[i - 1]),
            )
            up_move = highs[i] - highs[i - 1]
            down_move = lows[i - 1] - lows[i]
            plus_dm_i = up_move if (up_move > down_move and up_move > 0) else 0.0
            minus_dm_i = down_move if (down_move > up_move and down_move > 0) else 0.0
            tr.append(tr_i)
            plus_dm.append(plus_dm_i)
            minus_dm.append(minus_dm_i)

        atr = _wilder_smooth(tr, period)
        plus_dm_s = _wilder_smooth(plus_dm, period)
        minus_dm_s = _wilder_smooth(minus_dm, period)

        # +DI / -DI / DX series, all aligned at the same bar offsets.
        dx: list[float] = []
        for atr_v, pdm, mdm in zip(atr, plus_dm_s, minus_dm_s):
            if atr_v <= 0:
                dx.append(0.0)
                continue
            pdi = 100.0 * pdm / atr_v
            mdi = 100.0 * mdm / atr_v
            denom = pdi + mdi
            dx.append(100.0 * abs(pdi - mdi) / denom if denom > 0 else 0.0)

        # ADX = Wilder-smooth of DX over `period` — another `period` lag.
        adx = _wilder_smooth(dx, period)
        # Wilder smoothing returns sum-based first value; normalize to an
        # average so the scale is 0-100.
        adx_norm = [v / period for v in adx]

        # Align timestamps. TR/DM start at candles[1], so first smoothed
        # value covers candles[1..period] → index `period`. ADX adds another
        # `period-1` lag, so ADX[0] lands at candles[2*period - 1].
        start_idx = 2 * period - 1
        for i, v in enumerate(adx_norm):
            ts_idx = start_idx + i
            if ts_idx >= len(timestamps):
                break
            result.values.append([timestamps[ts_idx], round(v, 2)])

        # Meta — current ADX + directional bias from last +DI/-DI
        if result.values:
            current = result.values[-1][1]
            if current < 20:
                label = "no trend (range/chop)"
            elif current < 25:
                label = "trend emerging"
            elif current < 50:
                label = "trending"
            else:
                label = "extreme trend"

            # Last +DI / -DI for direction hint
            if atr and plus_dm_s and minus_dm_s:
                last_pdi = 100.0 * plus_dm_s[-1] / atr[-1] if atr[-1] > 0 else 0.0
                last_mdi = 100.0 * minus_dm_s[-1] / atr[-1] if atr[-1] > 0 else 0.0
                direction = "bullish" if last_pdi > last_mdi else "bearish"
            else:
                last_pdi = last_mdi = 0.0
                direction = "unknown"

            # Rising vs falling: slope over last 5 bars
            if len(result.values) >= 5:
                delta = result.values[-1][1] - result.values[-5][1]
                slope = "rising" if delta > 0 else ("falling" if delta < 0 else "flat")
            else:
                slope = "unknown"

            result.meta = {
                "current": round(current, 2),
                "label": label,
                "direction_hint": direction,
                "slope": slope,
                "plus_di": round(last_pdi, 2),
                "minus_di": round(last_mdi, 2),
                "period": period,
            }
        return result
