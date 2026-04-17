"""Simplified Wyckoff phase classifier.

Richard Wyckoff's four-phase cycle — accumulation, markup, distribution,
markdown — reduced to a mechanical classifier. For each bar (once we
have a full `window` of history) we compute:

  • range_tightness   = (recent range) / (longer-term range)
  • range_position    = where the recent close sits in the longer range
  • obv_slope         = OBV trend over the window (reusing the registered
                         obv signal for consistency)

Rules (default window=50):
  • tight range (tightness < 0.6) at the TOP of longer range + falling
    OBV  → DISTRIBUTION
  • tight range at the BOTTOM of longer range + rising OBV
                                           → ACCUMULATION
  • recent close breaking ABOVE the longer range + rising OBV
                                           → MARKUP
  • recent close breaking BELOW the longer range + falling OBV
                                           → MARKDOWN
  • else                                    → UNKNOWN

Phases are encoded numerically for the chart (0=unknown, 1=accumulation,
2=markup, 3=distribution, 4=markdown) and the client can step-render.
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


_PHASE_CODE = {
    "unknown": 0,
    "accumulation": 1,
    "markup": 2,
    "distribution": 3,
    "markdown": 4,
}


@register
class WyckoffPhase(Signal):
    card = SignalCard(
        name="Wyckoff Phase (simplified)",
        slug="wyckoff_phase",
        category="accumulation",
        what=(
            "Labels each bar with a Wyckoff-cycle phase — accumulation, "
            "markup, distribution, markdown, or unknown — using a "
            "rolling window to compare the recent (last 20%) range to "
            "the full window range plus an OBV slope read. Encodes the "
            "label as 0-4 for charting; `meta.current_phase` carries "
            "the human-readable label and `meta.last_change_index` "
            "notes when the phase last changed."
        ),
        basis=(
            "Richard Wyckoff's market cycle (1920s), codified in "
            "'The Wyckoff Method of Trading and Investing in Stocks' "
            "(SMI course, 1930s) and the Wyckoff/Hank Pruden lineage. "
            "This is a deliberately simplified classifier — true "
            "Wyckoff analysis requires swing points, springs, and "
            "upthrusts that don't reduce cleanly to mechanical rules."
        ),
        how_to_read=(
            "• ACCUMULATION: tight range near window low + rising "
            "OBV. Smart money building position; expect markup to "
            "follow. This is the buy window.\n"
            "• MARKUP: recent close above the window range + OBV "
            "confirming. Trend phase — ride it until volume shows "
            "exhaustion.\n"
            "• DISTRIBUTION: tight range near window high + falling "
            "OBV. Smart money unwinding; expect markdown. Tighten "
            "longs or go flat.\n"
            "• MARKDOWN: recent close below the window range + OBV "
            "confirming. Downtrend phase.\n"
            "• UNKNOWN: none of the above cleanly apply — sit on "
            "hands or use other signals.\n"
            "• A change in phase_code is the tradeable event. Watch "
            "for accumulation→markup and distribution→markdown "
            "transitions specifically."
        ),
        failure_modes=(
            "• This is a mechanical approximation — real Wyckoff "
            "involves swing-point analysis (PS, SC, AR, ST, Spring, "
            "Test, SOS, LPS) that isn't captured here.\n"
            "• Requires window (50) + OBV warmup. Early bars stay "
            "'unknown' until the window fills.\n"
            "• Choppy non-trending markets produce frequent phase "
            "flips; treat rapid oscillation between labels as 'no "
            "regime' rather than signal.\n"
            "• Default window=50 is tuned for daily/4h charts; may "
            "need re-tuning on 1m/5m timeframes."
        ),
        inputs="high, low, close, volume",
        params={"window": 50, "recent_frac": 0.2, "tightness_thresh": 0.6},
    )
    chart_spec = ChartSpec(
        placement="subpane",
        series_type="line",
        color="primary",
        axis="oscillator",
        series_name="Wyckoff Phase",
        priority=0,
    )

    def compute(self, candles: list[Candle], **params: Any) -> SignalResult:
        result = self.new_result()
        window = int(params.get("window", self.card.params["window"]))
        recent_frac = float(params.get("recent_frac",
                                       self.card.params["recent_frac"]))
        tightness_thresh = float(params.get("tightness_thresh",
                                            self.card.params["tightness_thresh"]))
        if window < 5:
            window = 5
        if len(candles) < window:
            result.meta = {"reason": f"need ≥{window} candles"}
            return result

        obv_res = registry_compute("obv", candles)
        obv_vals = [v for _, v in obv_res.values]
        if len(obv_vals) != len(candles):
            result.meta = {"reason": "OBV length mismatch"}
            return result

        highs = [_to_float(c["h"]) for c in candles]
        lows = [_to_float(c["l"]) for c in candles]
        closes = [_to_float(c["c"]) for c in candles]
        times = [int(c["t"]) for c in candles]

        recent_len = max(2, int(window * recent_frac))

        phases: list[str] = []
        # Pad the warmup region with unknown.
        for i in range(len(candles)):
            if i < window - 1:
                phases.append("unknown")
                continue

            w_hi = max(highs[i - window + 1:i + 1])
            w_lo = min(lows[i - window + 1:i + 1])
            w_range = w_hi - w_lo

            r_hi = max(highs[i - recent_len + 1:i + 1])
            r_lo = min(lows[i - recent_len + 1:i + 1])
            r_range = r_hi - r_lo

            # Position of recent window's midpoint inside the long window.
            if w_range > 0:
                r_mid = (r_hi + r_lo) / 2.0
                position = (r_mid - w_lo) / w_range  # 0..1
                tightness = r_range / w_range  # small = tight
            else:
                position = 0.5
                tightness = 1.0

            obv_delta = obv_vals[i] - obv_vals[i - window + 1]
            close_now = closes[i]

            phase = "unknown"
            # Breakout / breakdown first — they override the tight-range labels
            # when the recent close has escaped the full-window range.
            # Use the prior-window extremes (excluding the very last bar) as
            # the reference, so a close above signals a genuine break.
            prior_hi = max(highs[i - window + 1:i])
            prior_lo = min(lows[i - window + 1:i])
            if close_now > prior_hi and obv_delta > 0:
                phase = "markup"
            elif close_now < prior_lo and obv_delta < 0:
                phase = "markdown"
            elif tightness < tightness_thresh:
                if position >= 0.6 and obv_delta < 0:
                    phase = "distribution"
                elif position <= 0.4 and obv_delta > 0:
                    phase = "accumulation"
            phases.append(phase)

        result.values = [[times[i], _PHASE_CODE[phases[i]]]
                         for i in range(len(candles))]

        # Find last phase change (scan backward)
        last_change_index = 0
        for i in range(len(phases) - 1, 0, -1):
            if phases[i] != phases[i - 1]:
                last_change_index = i
                break

        result.meta = {
            "window": window,
            "current_phase": phases[-1],
            "current_phase_code": _PHASE_CODE[phases[-1]],
            "last_change_index": last_change_index,
            "last_change_time": times[last_change_index] if last_change_index else times[0],
            "phase_counts": {
                k: phases.count(k) for k in _PHASE_CODE.keys()
            },
            "bar_count": len(candles),
        }
        return result
