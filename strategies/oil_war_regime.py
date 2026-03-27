"""Oil War Regime strategy — professional-grade mean-reversion with geopolitical overlay.

EVIDENCE FROM DATA:
  - BRENTOIL on HL has 128% annualized vol (3-4x normal Brent)
  - Return autocorrelation is -0.075 (MEAN-REVERTING — overshoots correct)
  - Up hours 55% but down moves are bigger (-0.89% vs +0.81%)
  - Volume clusters at $96-101 = institutional support zone
  - This is NOT a normal oil market — it's a leveraged perp on a war commodity

WHAT PROFESSIONALS DO (adapted for HL perps):

  1. REGIME DETECTION — Know whether to fade or trend-follow:
     - STRUCTURAL DISRUPTION: backwardation deepening, vol expanding → TREND FOLLOW
     - POST-SHOCK FADE: vol contracting, price extended from mean → FADE
     - ACCUMULATION: low vol, price near support cluster → SCALE IN LONG

  2. MEAN REVERSION AT EXTREMES — the core edge:
     - 128% vol means price regularly overshoots 2-3% from fair value
     - Negative autocorrelation CONFIRMS mean reversion works here
     - Buy when price drops >2 ATR below EMA, sell when >2 ATR above
     - Position size inversely proportional to distance (further = bigger)

  3. ASYMMETRIC BIAS — war premium:
     - Long entries are 2x the size of short entries (bullish bias)
     - Shorts only as hedges/take-profit, never naked conviction shorts
     - Support zone ($96-101) gets extra size on dips

  4. VOLATILITY-ADJUSTED EVERYTHING:
     - ATR-based stops, targets, and sizing
     - When vol expands → reduce size, widen stops
     - When vol contracts → increase size, tighten stops

  5. TIME-OF-DAY AWARENESS:
     - War news breaks outside US market hours (Middle East evening = US morning)
     - European open (02:00-04:00 UTC) often sees sharp moves
     - US open (13:30 UTC) gets the EIA data reaction
"""
from __future__ import annotations

import math
from collections import deque
from enum import Enum
from typing import List, Optional

from common.models import MarketSnapshot, StrategyDecision
from sdk.strategy_sdk.base import BaseStrategy, StrategyContext


# ── Regime Detection ──────────────────────────────────────────────
class Regime(Enum):
    ACCUMULATION = "accumulation"      # Low vol, near support → scale in long
    TRENDING_UP = "trending_up"        # Strong uptrend → trail longs, no fade
    MEAN_REVERT = "mean_revert"        # Normal vol → fade extremes
    HIGH_VOL_CHAOS = "high_vol_chaos"  # Extreme vol → reduce size, widen stops


# ── Parameters ────────────────────────────────────────────────────
EMA_FAST = 12
EMA_SLOW = 50
ATR_PERIOD = 24

# Mean reversion thresholds (in ATR units)
MR_ENTRY_ATR = 1.5         # Enter fade when price is 1.5 ATR from EMA
MR_AGGRESSIVE_ATR = 2.5    # Aggressive entry at 2.5 ATR (bigger size)
MR_EXTREME_ATR = 3.5       # Extreme — max conviction

# Take profit / stops (in ATR units)
TP_ATR = 1.0               # Take profit when price reverts 1 ATR toward mean
STOP_ATR = 3.0             # Hard stop at 3 ATR beyond entry
TRAIL_ATR = 1.5            # Trailing stop distance once in profit

# Position sizing
BASE_SIZE_PCT = 0.10        # 10% of equity base
LONG_BIAS_MULT = 1.5        # Longs are 1.5x larger than shorts
MAX_POSITION_PCT = 0.40     # Max 40% equity exposure
SUPPORT_ZONE = (94, 102)    # Volume-weighted support zone from data

# Volatility regime thresholds
VOL_LOW = 0.008             # Below this hourly stdev = low vol
VOL_HIGH = 0.018            # Above this = high vol chaos
VOL_EXTREME = 0.030         # Above this = don't trade

# Regime detection
MIN_HISTORY = EMA_SLOW + ATR_PERIOD + 20


def _ema(values: list, span: int) -> float:
    if not values:
        return 0.0
    alpha = 2.0 / (span + 1)
    ema = values[0]
    for v in values[1:]:
        ema = alpha * v + (1 - alpha) * ema
    return ema


def _atr(highs: list, lows: list, closes: list, period: int) -> float:
    if len(closes) < 2:
        return 0.0
    trs = []
    for i in range(1, len(closes)):
        tr = max(highs[i] - lows[i], abs(highs[i] - closes[i-1]), abs(lows[i] - closes[i-1]))
        trs.append(tr)
    if len(trs) < period:
        return sum(trs) / len(trs) if trs else 0.0
    atr = sum(trs[:period]) / period
    for tr in trs[period:]:
        atr = (atr * (period - 1) + tr) / period
    return atr


def _rolling_stdev(returns: list, window: int) -> float:
    if len(returns) < window:
        return 0.0
    recent = returns[-window:]
    mean = sum(recent) / len(recent)
    variance = sum((r - mean) ** 2 for r in recent) / len(recent)
    return math.sqrt(variance)


class OilWarRegimeStrategy(BaseStrategy):
    """War-regime oil trading: mean reversion at extremes with bullish structural bias.

    The key insight: BRENTOIL on HL is mean-reverting (negative autocorrelation)
    with 128% annualized vol. This means every overshoot corrects. We exploit
    that, but with a long bias because the fundamental supply picture is bullish.
    """

    def __init__(self, strategy_id: str = "oil_war_regime"):
        super().__init__(strategy_id=strategy_id)

        _maxlen = MIN_HISTORY + 20
        self.closes: deque = deque(maxlen=_maxlen)
        self.highs: deque = deque(maxlen=_maxlen)
        self.lows: deque = deque(maxlen=_maxlen)
        self.returns: deque = deque(maxlen=_maxlen)

        # Trade state
        self._entry_price: float = 0.0
        self._entry_side: str = ""
        self._peak_pnl_pct: float = 0.0
        self._candles_held: int = 0

    def on_tick(
        self,
        snapshot: MarketSnapshot,
        context: Optional[StrategyContext] = None,
    ) -> List[StrategyDecision]:
        mid = snapshot.mid_price
        if mid <= 0:
            return []

        # Get OHLCV from candle data if available (backtest), else from snapshot
        candle = context.meta.get("candle") if context else None
        if candle:
            high = float(candle["h"])
            low = float(candle["l"])
        else:
            high = snapshot.ask if snapshot.ask > 0 else mid
            low = snapshot.bid if snapshot.bid > 0 else mid

        # Track returns for vol calculation
        if self.closes:
            ret = (mid - self.closes[-1]) / self.closes[-1]
            self.returns.append(ret)

        self.closes.append(mid)
        self.highs.append(high)
        self.lows.append(low)

        if len(self.closes) < MIN_HISTORY:
            return []

        # ── Compute indicators ────────────────────────────────────
        closes = list(self.closes)
        highs = list(self.highs)
        lows = list(self.lows)

        ema_fast = _ema(closes, EMA_FAST)
        ema_slow = _ema(closes, EMA_SLOW)
        atr = _atr(highs, lows, closes, ATR_PERIOD)
        hourly_vol = _rolling_stdev(list(self.returns), 20)

        if atr <= 0:
            return []

        # Fair value estimate: blend of fast and slow EMA
        # (fast-weighted in trends, slow-weighted in ranges)
        fair_value = ema_fast * 0.4 + ema_slow * 0.6

        # Distance from fair value in ATR units
        deviation_atr = (mid - fair_value) / atr

        # ── Detect regime ─────────────────────────────────────────
        regime = self._detect_regime(mid, ema_fast, ema_slow, hourly_vol, atr)

        # ── Position state ────────────────────────────────────────
        pos_qty = 0.0
        equity = 10_000.0
        if context:
            pos_qty = context.position_qty
            equity = context.meta.get("account_value", 10_000.0)

        in_position = abs(pos_qty) > 0.001
        decisions = []

        # ── MANAGE EXISTING POSITION ──────────────────────────────
        if in_position:
            self._candles_held += 1
            if self._entry_side == "long":
                pnl_pct = (mid - self._entry_price) / self._entry_price * 100
            else:
                pnl_pct = (self._entry_price - mid) / self._entry_price * 100

            self._peak_pnl_pct = max(self._peak_pnl_pct, pnl_pct)

            exit_reason = self._check_exit(mid, fair_value, atr, pnl_pct, regime)
            if exit_reason:
                close_side = "short" if self._entry_side == "long" else "long"
                decisions.append(StrategyDecision(
                    action="place_order",
                    side=close_side,
                    size=abs(pos_qty),
                    price=mid,
                    reason=f"EXIT [{regime.value}]: {exit_reason} | pnl={pnl_pct:+.1f}% held={self._candles_held}h",
                ))
                self._reset()
            return decisions

        # ── DON'T TRADE in extreme vol ────────────────────────────
        if regime == Regime.HIGH_VOL_CHAOS and hourly_vol > VOL_EXTREME:
            return []  # Sit out the chaos — don't be the one getting liquidated

        # ── GENERATE ENTRY SIGNALS ────────────────────────────────
        entry = self._check_entry(mid, fair_value, deviation_atr, atr, regime, equity, hourly_vol)
        if entry:
            decisions.append(entry)

        return decisions

    def _detect_regime(self, price: float, ema_f: float, ema_s: float,
                       hourly_vol: float, atr: float) -> Regime:
        """Classify current market regime."""
        if hourly_vol > VOL_HIGH:
            return Regime.HIGH_VOL_CHAOS

        if hourly_vol < VOL_LOW and SUPPORT_ZONE[0] <= price <= SUPPORT_ZONE[1]:
            return Regime.ACCUMULATION

        # Strong trend: both EMAs aligned and price well above
        if ema_f > ema_s * 1.01 and price > ema_f:
            return Regime.TRENDING_UP

        return Regime.MEAN_REVERT

    def _check_entry(self, price: float, fair_value: float, dev_atr: float,
                     atr: float, regime: Regime, equity: float,
                     hourly_vol: float) -> Optional[StrategyDecision]:
        """Generate entry signal based on regime and deviation."""

        side = ""
        size_mult = 1.0
        reason_parts = []

        if regime == Regime.ACCUMULATION:
            # Low vol near support — scale in long
            if dev_atr < 0:  # Below fair value
                side = "long"
                size_mult = 1.2  # Extra size in accumulation
                reason_parts.append(f"accumulation_buy dev={dev_atr:.1f}ATR")

        elif regime == Regime.TRENDING_UP:
            # Only buy dips in uptrend, never short
            if dev_atr < -MR_ENTRY_ATR:
                side = "long"
                size_mult = 1.0
                reason_parts.append(f"trend_dip_buy dev={dev_atr:.1f}ATR")

        elif regime == Regime.MEAN_REVERT:
            # Core strategy: fade extremes
            if dev_atr < -MR_ENTRY_ATR:
                side = "long"
                if dev_atr < -MR_AGGRESSIVE_ATR:
                    size_mult = 1.5
                    reason_parts.append(f"aggressive_long dev={dev_atr:.1f}ATR")
                elif dev_atr < -MR_EXTREME_ATR:
                    size_mult = 2.0
                    reason_parts.append(f"EXTREME_long dev={dev_atr:.1f}ATR")
                else:
                    reason_parts.append(f"mr_long dev={dev_atr:.1f}ATR")

            elif dev_atr > MR_ENTRY_ATR:
                # Short — but smaller size (war premium = don't fight the supply squeeze)
                side = "short"
                size_mult = 0.5  # Half size for shorts
                if dev_atr > MR_AGGRESSIVE_ATR:
                    size_mult = 0.8
                    reason_parts.append(f"aggressive_short dev={dev_atr:.1f}ATR")
                else:
                    reason_parts.append(f"mr_short dev={dev_atr:.1f}ATR")

        elif regime == Regime.HIGH_VOL_CHAOS:
            # Only trade extreme extremes in chaos
            if dev_atr < -MR_EXTREME_ATR:
                side = "long"
                size_mult = 0.7  # Reduced size in chaos
                reason_parts.append(f"chaos_extreme_buy dev={dev_atr:.1f}ATR")

        if not side:
            return None

        # Apply war bias
        if side == "long":
            size_mult *= LONG_BIAS_MULT

        # Support zone bonus
        if side == "long" and SUPPORT_ZONE[0] <= price <= SUPPORT_ZONE[1]:
            size_mult *= 1.3
            reason_parts.append("in_support_zone")

        # Volatility-adjust sizing (inverse: high vol = smaller)
        vol_adj = 1.0
        if hourly_vol > 0:
            target_vol = 0.012  # Target 1.2% hourly vol exposure
            vol_adj = min(2.0, max(0.3, target_vol / hourly_vol))

        # Calculate position size
        size_pct = BASE_SIZE_PCT * size_mult * vol_adj
        size_pct = min(size_pct, MAX_POSITION_PCT)
        size_usd = equity * size_pct
        size = size_usd / price if price > 0 else 0

        if size <= 0:
            return None

        self._entry_price = price
        self._entry_side = side
        self._peak_pnl_pct = 0.0
        self._candles_held = 0

        reason = (
            f"ENTRY [{regime.value}] {side.upper()}: "
            f"{' | '.join(reason_parts)} "
            f"| fv={fair_value:.2f} atr={atr:.2f} vol={hourly_vol:.4f} "
            f"| size=${size_usd:.0f} ({size_pct*100:.0f}%)"
        )

        return StrategyDecision(
            action="place_order",
            side=side,
            size=size,
            price=price,
            reason=reason,
        )

    def _check_exit(self, price: float, fair_value: float, atr: float,
                    pnl_pct: float, regime: Regime) -> str:
        """Check if we should exit the current position."""

        # 1. Take profit: price has reverted toward fair value
        if self._entry_side == "long":
            tp_price = self._entry_price + TP_ATR * atr
            stop_price = self._entry_price - STOP_ATR * atr
        else:
            tp_price = self._entry_price - TP_ATR * atr
            stop_price = self._entry_price + STOP_ATR * atr

        if self._entry_side == "long" and price >= tp_price:
            return f"take_profit target={tp_price:.2f}"
        if self._entry_side == "short" and price <= tp_price:
            return f"take_profit target={tp_price:.2f}"

        # 2. Hard stop
        if self._entry_side == "long" and price <= stop_price:
            return f"stop_loss stop={stop_price:.2f}"
        if self._entry_side == "short" and price >= stop_price:
            return f"stop_loss stop={stop_price:.2f}"

        # 3. Trailing stop (once we've seen > 1% profit)
        if self._peak_pnl_pct > 1.0:
            trail_dist = TRAIL_ATR * atr
            if self._entry_side == "long":
                trail_price = self._entry_price + (self._peak_pnl_pct / 100 * self._entry_price) - trail_dist
                if price <= trail_price:
                    return f"trailing_stop peak={self._peak_pnl_pct:.1f}%"
            else:
                trail_price = self._entry_price - (self._peak_pnl_pct / 100 * self._entry_price) + trail_dist
                if price >= trail_price:
                    return f"trailing_stop peak={self._peak_pnl_pct:.1f}%"

        # 4. Time stop — 12 hours max hold for mean reversion trades
        if self._candles_held >= 12 and regime == Regime.MEAN_REVERT:
            return f"time_stop 12h"

        # 5. Regime change — if we're long in MR and regime shifts to chaos
        if regime == Regime.HIGH_VOL_CHAOS and self._candles_held > 2:
            if pnl_pct > 0:
                return f"regime_change_exit (chaos, locking profit)"

        return ""

    def _reset(self):
        self._entry_price = 0.0
        self._entry_side = ""
        self._peak_pnl_pct = 0.0
        self._candles_held = 0
