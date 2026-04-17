"""Volume Spread Analysis (VSA) — Tom Williams / Richard Wyckoff lineage.

For each bar, classify effort (volume vs its 20-bar average) and result
(range/spread vs its 20-bar average). Emit markers only for meaningful
effort/result divergences:

  • High/ultra effort + narrow spread   → ABSORPTION (smart money
    accepting the offered supply/demand without price moving — a
    fingerprint of professional activity).
  • Low effort + wide spread             → NO SUPPLY / NO DEMAND
    (price moves on nothing — easy markup or markdown, very bullish
    or bearish depending on direction).
  • Ultra effort + wide spread down-bar → CLIMACTIC SELLING (stopping
    volume, often near capitulation lows).
  • Ultra effort + wide spread up-bar   → CLIMACTIC BUYING (buying
    climax, often near tops).

All other bars are silent — VSA's value is the scarce signal, not the
noise of every bar.
"""
from __future__ import annotations

import statistics
from typing import Any

from common.signals.base import Candle, ChartSpec, Signal, SignalCard, SignalResult
from common.signals.registry import register


def _to_float(x: Any) -> float:
    try:
        return float(x)
    except (TypeError, ValueError):
        return 0.0


def _effort(v: float, avg: float) -> str:
    if avg <= 0:
        return "normal"
    r = v / avg
    if r >= 2.5:
        return "ultra"
    if r >= 1.5:
        return "high"
    if r <= 0.5:
        return "low"
    return "normal"


def _result_label(spread: float, avg_spread: float) -> str:
    if avg_spread <= 0:
        return "normal"
    r = spread / avg_spread
    if r >= 1.5:
        return "wide"
    if r <= 0.5:
        return "narrow"
    return "normal"


@register
class VSA(Signal):
    card = SignalCard(
        name="Volume Spread Analysis (effort vs result)",
        slug="vsa",
        category="accumulation",
        what=(
            "Classifies each bar's volume as effort (vs the 20-bar "
            "volume average) and its high-low range as result (vs the "
            "20-bar spread average). Flags bars where effort and "
            "result disagree — the classic Wyckoff/Williams "
            "fingerprint of professional activity. Emits markers only "
            "on the interesting cases: absorption, no-supply/no-"
            "demand, and climactic effort bars."
        ),
        basis=(
            "Richard Wyckoff's original effort-vs-result principle "
            "(1910s) formalized by Tom Williams in 'Master the "
            "Markets' (Williams, 1993) and later 'The Undeclared "
            "Secrets That Drive the Stock Market' (Williams, 2005). "
            "Thresholds (1.5x, 2.5x, 0.5x) are standard defaults used "
            "in commercial VSA software."
        ),
        how_to_read=(
            "• ABSORPTION (high/ultra volume + narrow spread): smart "
            "money is absorbing the opposing side without letting "
            "price move. Watch for the break that follows.\n"
            "• NO SUPPLY (low volume + wide up-bar): nobody selling "
            "into strength — bullish, path of least resistance is up.\n"
            "• NO DEMAND (low volume + wide down-bar): nobody buying "
            "weakness — bearish.\n"
            "• CLIMAX (ultra volume + wide spread): exhaustion "
            "candidate; up-climax near tops, down-climax near bottoms. "
            "Look for a test bar with low volume and narrow spread "
            "within a few bars to confirm.\n"
            "• Normal bars are silent on purpose — VSA only talks when "
            "it has something to say."
        ),
        failure_modes=(
            "• Requires at least 20 bars of history to compute "
            "averages; early bars get no markers.\n"
            "• Very low-volume markets produce unstable averages — "
            "ratios spike on any slightly-above-normal bar.\n"
            "• News gaps create apparent wide-spread bars that are "
            "really two separate regimes joined by the close — "
            "discount markers over known events.\n"
            "• Intraday VSA on very short timeframes (1m) is noisy; "
            "the tradition is 5m/15m and higher."
        ),
        inputs="high, low, open, close, volume",
        params={"window": 20, "effort_high": 1.5, "effort_ultra": 2.5,
                "effort_low": 0.5, "spread_wide": 1.5, "spread_narrow": 0.5},
    )
    chart_spec = ChartSpec(
        placement="overlay",
        series_type="markers",
        color="primary",
        axis="price",
        series_name="VSA",
        priority=6,
    )

    def compute(self, candles: list[Candle], **params: Any) -> SignalResult:
        result = self.new_result()
        window = int(params.get("window", self.card.params["window"]))
        if window < 2:
            window = 2
        if len(candles) < window + 1:
            result.meta = {"reason": f"need ≥{window+1} candles"}
            return result

        vols = [_to_float(c["v"]) for c in candles]
        spreads = [_to_float(c["h"]) - _to_float(c["l"]) for c in candles]
        opens = [_to_float(c["o"]) for c in candles]
        closes = [_to_float(c["c"]) for c in candles]
        times = [int(c["t"]) for c in candles]

        absorption = no_supply_demand = climactic = 0
        for i in range(window, len(candles)):
            vol_avg = statistics.mean(vols[i - window:i])
            sp_avg = statistics.mean(spreads[i - window:i])
            eff = _effort(vols[i], vol_avg)
            res = _result_label(spreads[i], sp_avg)
            up_bar = closes[i] > opens[i]
            down_bar = closes[i] < opens[i]

            marker: dict[str, Any] | None = None
            if eff in ("high", "ultra") and res == "narrow":
                marker = {
                    "time": times[i],
                    "position": "inBar",
                    "color": "primary",
                    "shape": "circle",
                    "text": f"Absorption ({eff} vol / narrow)",
                    "price": round(closes[i], 6),
                    "kind": "absorption",
                }
                absorption += 1
            elif eff == "low" and res == "wide":
                label = "No supply" if up_bar else "No demand" if down_bar else "Low-effort wide"
                marker = {
                    "time": times[i],
                    "position": "inBar",
                    "color": "positive" if up_bar else "negative",
                    "shape": "diamond",
                    "text": label,
                    "price": round(closes[i], 6),
                    "kind": "no_supply_demand",
                }
                no_supply_demand += 1
            elif eff == "ultra" and res == "wide":
                label = "Buying climax" if up_bar else "Selling climax" if down_bar else "Climactic"
                marker = {
                    "time": times[i],
                    "position": "above" if down_bar else "below",
                    "color": "negative" if up_bar else "positive",
                    "shape": "arrowDown" if up_bar else "arrowUp",
                    "text": label,
                    "price": round(closes[i], 6),
                    "kind": "climax",
                }
                climactic += 1
            if marker is not None:
                result.markers.append(marker)

        result.meta = {
            "window": window,
            "absorption_count": absorption,
            "no_supply_demand_count": no_supply_demand,
            "climactic_count": climactic,
            "total_markers": len(result.markers),
            "bar_count": len(candles),
        }
        return result
