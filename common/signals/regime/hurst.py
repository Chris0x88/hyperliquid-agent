"""Hurst exponent — memory / persistence in a price series.

H > 0.5 = trending (persistent, long memory). H = 0.5 = random walk.
H < 0.5 = mean-reverting (anti-persistent).

Used by the regime classifier to distinguish genuine trends from
pure noise, complementing ADX (which measures trend MAGNITUDE, while
Hurst measures trend QUALITY / predictability).

Implementation: aggregated variance (variance ratio) method — compute
the standard deviation of cumulative returns over a set of lags; fit
a line in log-log space; slope ≈ Hurst exponent. Fast and reasonable
for rolling-window use, unlike R/S analysis which needs O(N²).
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
    var = sum((x - m) ** 2 for x in xs) / (len(xs) - 1)
    return math.sqrt(var)


def _linfit_slope(xs: list[float], ys: list[float]) -> float:
    """Least-squares slope (no intercept needed)."""
    if len(xs) < 2 or len(xs) != len(ys):
        return 0.0
    mx, my = _mean(xs), _mean(ys)
    num = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    den = sum((x - mx) ** 2 for x in xs)
    return num / den if den > 0 else 0.0


def _hurst_window(returns: list[float]) -> float | None:
    """Hurst estimate over one window via aggregated variance method.

    Returns None if the window is too short or variance is degenerate.
    """
    n = len(returns)
    if n < 20:
        return None

    lags = [2, 4, 8, 16]
    lags = [L for L in lags if L * 2 <= n]
    if len(lags) < 3:
        return None

    log_lags: list[float] = []
    log_stds: list[float] = []
    for lag in lags:
        # Aggregate: sum of `lag` consecutive returns = lag-period log-return
        aggregated = [
            sum(returns[i : i + lag]) for i in range(0, n - lag + 1, lag)
        ]
        if len(aggregated) < 2:
            continue
        s = _std(aggregated)
        if s <= 0:
            continue
        log_lags.append(math.log(lag))
        log_stds.append(math.log(s))

    if len(log_lags) < 3:
        return None

    h = _linfit_slope(log_lags, log_stds)
    # Clamp to the interpretable range — noisy estimators can drift outside [0,1]
    return max(0.0, min(1.0, h))


@register
class Hurst(Signal):
    card = SignalCard(
        name="Hurst Exponent",
        slug="hurst",
        category="regime",
        what=(
            "Rolling Hurst exponent — measures the long-memory / persistence "
            "of price. Estimated via aggregated-variance method over a "
            "configurable window (default 100 bars of log returns)."
        ),
        basis=(
            "Harold Edwin Hurst, 'Long-term storage capacity of reservoirs' "
            "(Transactions of the American Society of Civil Engineers, 1951). "
            "Generalized for financial time series by Mandelbrot (1960s–70s) "
            "and widely used in quantitative finance."
        ),
        how_to_read=(
            "• H ≈ 0.5 → random walk. Efficient market regime. Technical "
            "signals have weak edge here.\n"
            "• H > 0.55 → persistent / trending. Returns are positively "
            "autocorrelated — trends tend to continue. Momentum strategies "
            "favored.\n"
            "• H < 0.45 → anti-persistent / mean-reverting. Returns "
            "negatively autocorrelated — fade extremes. Mean-reversion "
            "strategies favored.\n"
            "• H > 0.65 is a strong trending regime; H < 0.35 is strongly "
            "mean-reverting (rare, usually only in tight ranges)."
        ),
        failure_modes=(
            "• Noisy on small windows (<60 bars). Don't over-interpret "
            "single readings — watch the trend.\n"
            "• Regime-dependent: a 0.5 reading does NOT mean 'ignore this "
            "market'; it means the specific lag structure looks random.\n"
            "• Breaks down across regime transitions — the estimate "
            "smears the old and new regimes together until the window "
            "fills with the new one.\n"
            "• Can give false 'mean-reverting' readings during news-driven "
            "gap mean-reverts that are actually one-off events."
        ),
        inputs="close",
        params={"window": 100},
    )
    chart_spec = ChartSpec(
        placement="subpane",
        series_type="line",
        color="tertiary",
        axis="raw",
        series_name="Hurst",
        priority=0,
    )

    def compute(self, candles: list[Candle], **params: Any) -> Any:
        window = int(params.get("window", 100))
        result = self.new_result()

        if len(candles) < window + 1:
            result.meta = {"reason": f"need ≥{window + 1} bars for Hurst(window={window})"}
            return result

        closes = [_to_float(c["c"]) for c in candles]
        timestamps = [int(c["t"]) for c in candles]

        # Log returns
        log_returns: list[float] = []
        for i in range(1, len(closes)):
            if closes[i - 1] > 0 and closes[i] > 0:
                log_returns.append(math.log(closes[i] / closes[i - 1]))
            else:
                log_returns.append(0.0)

        # Rolling window Hurst
        for i in range(window, len(log_returns) + 1):
            window_returns = log_returns[i - window : i]
            h = _hurst_window(window_returns)
            if h is None:
                continue
            # log_returns[i-1] corresponds to candles[i], so timestamp index = i
            ts_idx = i
            if ts_idx < len(timestamps):
                result.values.append([timestamps[ts_idx], round(h, 4)])

        if result.values:
            current = result.values[-1][1]
            if current > 0.55:
                label = "trending (persistent)"
            elif current < 0.45:
                label = "mean-reverting (anti-persistent)"
            else:
                label = "random walk"
            result.meta = {
                "current": current,
                "label": label,
                "window": window,
            }
        return result
