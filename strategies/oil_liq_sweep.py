"""Oil Liquidation Sweep strategy — profit from leveraged bot liquidations.

Evidence from BRENTOIL data analysis (550 candles, 50 liquidation events):

  PATTERN: High-leverage bots get cascaded on volatility spikes. The candle
  shows a massive wick (price overshoots 2-5%) with 2-22x average volume,
  then mean-reverts within 1-6 hours.

  KEY INSIGHT FROM DATA:
  - After LONG_LIQD_DIP events, price rebounds +1-5% within 3h (in uptrend)
  - After SHORT_SQUEEZE events, pullback is small (-0.5% avg)
  - The 22.5x volume spike on 3/23 ($108→$88→$101) was the biggest sweep
  - Bots using >5x leverage get harvested on these moves

  STRATEGY:
  - Detect liquidation cascades in real-time via volume spike + large wick
  - Wait for the cascade to exhaust (confirmation candle)
  - Enter in the OPPOSITE direction of the cascade (buy the dip, short the pump)
  - But ONLY when aligned with the macro trend (bullish bias for oil)
  - Tight take-profit (capture the bounce, don't hold through)
  - Hard time-stop (exit if bounce doesn't happen within N candles)

  WHY THIS WORKS:
  - Liquidation cascades are forced selling — not information-driven
  - The forced seller is broke and gone — no follow-through
  - Market makers widen spreads during cascades = higher fill quality after
  - In a bullish supply squeeze, every dip is a buy

  RISK:
  - Max 3-5x leverage (we are NOT the ones getting liquidated)
  - Position size scales with cascade magnitude (bigger sweep = bigger bounce)
  - Time-stop prevents holding losers (if no bounce in 4h, thesis is wrong)

Designed for: BRENTOIL-USDC on Hyperliquid (xyz:BRENTOIL)
Best interval: 1h (matches the liquidation cascade timeframe)
"""
from __future__ import annotations

import math
from collections import deque
from typing import List, Optional

from common.models import MarketSnapshot, StrategyDecision
from sdk.strategy_sdk.base import BaseStrategy, StrategyContext

# --- Detection parameters ---
VOLUME_SPIKE_MULT = 2.5    # Volume must be 2.5x avg to flag a cascade
WICK_RATIO_MIN = 0.40      # Wick must be >40% of total candle range
MIN_RANGE_PCT = 1.0        # Candle range must be >1% (filter noise)

# --- Trend filter ---
EMA_TREND = 50             # Only buy dips when above this, only short squeezes below
EMA_FAST = 9               # Short-term momentum

# --- Entry ---
CONFIRMATION_CANDLES = 1   # Wait 1 candle after the spike for confirmation
MAX_ENTRY_DISTANCE_PCT = 2.0  # Don't chase — entry must be within 2% of cascade close

# --- Exit ---
TAKE_PROFIT_PCT = 2.5      # Take profit at 2.5% from entry
STOP_LOSS_PCT = 3.0        # Hard stop at 3%
TIME_STOP_CANDLES = 6      # Exit if no TP hit within 6 hours
TRAIL_ACTIVATE_PCT = 1.5   # Start trailing after 1.5% profit
TRAIL_DISTANCE_PCT = 0.8   # Trail 0.8% below peak

# --- Position sizing ---
BASE_SIZE_PCT = 0.20       # 20% of equity per trade
MAX_SIZE_PCT = 0.35        # Up to 35% for extreme cascades (>5x vol)
VOLUME_SIZE_SCALE = True   # Bigger cascade = bigger position

# --- History ---
LOOKBACK = 60              # Track 60 candles of history
MIN_HISTORY = max(EMA_TREND + 5, LOOKBACK)


def _ema(values: list, span: int) -> float:
    if len(values) < 2:
        return values[-1] if values else 0.0
    alpha = 2.0 / (span + 1)
    ema = values[0]
    for v in values[1:]:
        ema = alpha * v + (1 - alpha) * ema
    return ema


class OilLiqSweepStrategy(BaseStrategy):
    """Detect and trade liquidation cascades on Brent Oil.

    Long-biased: primarily buys dips caused by long liquidations in a bullish trend.
    Will short-sell pumps from short squeezes only when trend is clearly overbought.
    """

    def __init__(
        self,
        strategy_id: str = "oil_liq_sweep",
        base_size_pct: float = BASE_SIZE_PCT,
        max_size_pct: float = MAX_SIZE_PCT,
    ):
        super().__init__(strategy_id=strategy_id)
        self.base_size_pct = base_size_pct
        self.max_size_pct = max_size_pct

        # Price/volume history
        self.closes: deque = deque(maxlen=MIN_HISTORY + 10)
        self.highs: deque = deque(maxlen=MIN_HISTORY + 10)
        self.lows: deque = deque(maxlen=MIN_HISTORY + 10)
        self.volumes: deque = deque(maxlen=MIN_HISTORY + 10)
        self.opens: deque = deque(maxlen=MIN_HISTORY + 10)

        # Cascade detection state
        self._cascade_detected: bool = False
        self._cascade_type: str = ""       # "LONG_LIQ" or "SHORT_SQUEEZE"
        self._cascade_close: float = 0.0   # Close price of the cascade candle
        self._cascade_volume_mult: float = 0.0
        self._cascade_wick_pct: float = 0.0
        self._confirmation_countdown: int = 0

        # Position state
        self._in_trade: bool = False
        self._entry_price: float = 0.0
        self._entry_side: str = ""
        self._peak_since_entry: float = 0.0
        self._trough_since_entry: float = float('inf')
        self._candles_in_trade: int = 0
        self._trailing_active: bool = False

    def on_tick(
        self,
        snapshot: MarketSnapshot,
        context: Optional[StrategyContext] = None,
    ) -> List[StrategyDecision]:
        mid = snapshot.mid_price
        if mid <= 0:
            return []

        # Use actual OHLCV data when available (backtest passes candle in meta)
        candle = context.meta.get("candle") if context else None
        if candle:
            open_px = float(candle["o"])
            high = float(candle["h"])
            low = float(candle["l"])
            vol = float(candle["v"])
        else:
            open_px = mid
            high = snapshot.ask if snapshot.ask > 0 else mid
            low = snapshot.bid if snapshot.bid > 0 else mid
            vol = snapshot.volume_24h if snapshot.volume_24h > 0 else 0

        self.closes.append(mid)
        self.highs.append(high)
        self.lows.append(low)
        self.volumes.append(vol)
        self.opens.append(open_px)

        if len(self.closes) < MIN_HISTORY:
            return []

        closes = list(self.closes)
        volumes = list(self.volumes)

        # Trend filter
        ema_trend = _ema(closes, EMA_TREND)
        ema_fast = _ema(closes, EMA_FAST)
        bullish_trend = mid > ema_trend
        bearish_trend = mid < ema_trend

        # Average volume (excluding current candle)
        avg_vol = sum(volumes[:-1]) / max(len(volumes) - 1, 1)

        # Get position state from context
        pos_qty = 0.0
        equity = 10_000.0
        if context:
            pos_qty = context.position_qty
            equity = context.meta.get("account_value", 10_000.0)

        self._in_trade = abs(pos_qty) > 0
        decisions = []

        # ========================================
        # MANAGE EXISTING TRADE
        # ========================================
        if self._in_trade:
            self._candles_in_trade += 1

            # Track peak/trough for trailing stop
            if self._entry_side == "long":
                if mid > self._peak_since_entry:
                    self._peak_since_entry = mid
                profit_pct = (mid - self._entry_price) / self._entry_price * 100
            else:
                if mid < self._trough_since_entry:
                    self._trough_since_entry = mid
                profit_pct = (self._entry_price - mid) / self._entry_price * 100

            # Check exits in priority order
            exit_reason = ""

            # 1. Take profit
            if profit_pct >= TAKE_PROFIT_PCT:
                exit_reason = f"take_profit ({profit_pct:+.1f}%)"

            # 2. Trailing stop (once activated)
            elif profit_pct >= TRAIL_ACTIVATE_PCT:
                self._trailing_active = True

            if self._trailing_active and not exit_reason:
                if self._entry_side == "long":
                    trail_stop = self._peak_since_entry * (1 - TRAIL_DISTANCE_PCT / 100)
                    if mid <= trail_stop:
                        exit_reason = f"trailing_stop (peak={self._peak_since_entry:.2f} trail={trail_stop:.2f})"
                else:
                    trail_stop = self._trough_since_entry * (1 + TRAIL_DISTANCE_PCT / 100)
                    if mid >= trail_stop:
                        exit_reason = f"trailing_stop (trough={self._trough_since_entry:.2f})"

            # 3. Hard stop loss
            if not exit_reason and profit_pct <= -STOP_LOSS_PCT:
                exit_reason = f"stop_loss ({profit_pct:+.1f}%)"

            # 4. Time stop — thesis failed, move on
            if not exit_reason and self._candles_in_trade >= TIME_STOP_CANDLES:
                exit_reason = f"time_stop ({self._candles_in_trade} candles, pnl={profit_pct:+.1f}%)"

            if exit_reason:
                close_side = "short" if self._entry_side == "long" else "long"
                decisions.append(StrategyDecision(
                    action="place_order",
                    side=close_side,
                    size=abs(pos_qty),
                    price=mid,
                    reason=f"EXIT: {exit_reason}",
                ))
                self._reset_trade_state()
                return decisions

            return []  # In trade, no exit triggered, hold

        # ========================================
        # DETECT NEW CASCADE
        # ========================================
        if self._confirmation_countdown > 0:
            self._confirmation_countdown -= 1
            if self._confirmation_countdown == 0:
                # Confirmation complete — check if we should enter
                entry = self._evaluate_entry(mid, ema_trend, bullish_trend, bearish_trend, equity)
                if entry:
                    decisions.append(entry)
                else:
                    self._cascade_detected = False
            return decisions

        # Scan current candle for cascade signature
        if not self._cascade_detected and avg_vol > 0:
            current_vol = volumes[-1]
            vol_mult = current_vol / avg_vol

            # Get candle metrics using actual OHLCV
            c_open = self.opens[-1]
            c_high = self.highs[-1]
            c_low = self.lows[-1]
            c_close = mid
            c_range = c_high - c_low
            c_body = abs(c_close - c_open)
            range_pct = (c_range / mid * 100) if mid > 0 else 0

            if c_range > 0:
                wick_ratio = (c_range - c_body) / c_range
            else:
                wick_ratio = 0

            # Cascade detection: volume spike + large wick + meaningful range
            if vol_mult >= VOLUME_SPIKE_MULT and wick_ratio >= WICK_RATIO_MIN and range_pct >= MIN_RANGE_PCT:
                # Classify the cascade using actual open/close
                upper_wick = c_high - max(c_close, c_open)
                lower_wick = min(c_close, c_open) - c_low

                if lower_wick > upper_wick * 1.3:
                    cascade_type = "LONG_LIQ"  # Longs got liquidated (price dumped)
                elif upper_wick > lower_wick * 1.3:
                    cascade_type = "SHORT_SQUEEZE"  # Shorts got squeezed (price pumped)
                else:
                    cascade_type = "BOTH_SIDES"

                self._cascade_detected = True
                self._cascade_type = cascade_type
                self._cascade_close = mid
                self._cascade_volume_mult = vol_mult
                self._cascade_wick_pct = wick_ratio * 100
                self._confirmation_countdown = CONFIRMATION_CANDLES

        return decisions

    def _evaluate_entry(self, mid: float, ema_trend: float, bullish: bool, bearish: bool, equity: float) -> Optional[StrategyDecision]:
        """After cascade + confirmation, decide whether to enter."""

        # Check distance from cascade close
        distance_pct = abs(mid - self._cascade_close) / self._cascade_close * 100
        if distance_pct > MAX_ENTRY_DISTANCE_PCT:
            self._cascade_detected = False
            return None

        side = ""
        reason_parts = []

        if self._cascade_type == "LONG_LIQ":
            # Longs got liquidated — buy the dip (if trend supports)
            if bullish or mid > ema_trend * 0.97:  # Allow 3% below trend for deep dips
                side = "long"
                reason_parts.append(f"buy_dip_after_long_liq")
            else:
                self._cascade_detected = False
                return None  # Too far below trend, dip might be real

        elif self._cascade_type == "SHORT_SQUEEZE":
            # Shorts got squeezed — fade the pump
            # But in a bullish oil market, fading pumps is dangerous
            # Only fade if CLEARLY overbought
            if bearish:
                side = "short"
                reason_parts.append(f"fade_squeeze")
            else:
                # In bullish trend, a short squeeze just adds fuel — BUY
                side = "long"
                reason_parts.append(f"ride_squeeze_momentum")

        elif self._cascade_type == "BOTH_SIDES":
            # Both sides got hit — enter in trend direction
            if bullish:
                side = "long"
                reason_parts.append(f"buy_chaos_dip")
            elif bearish:
                side = "short"
                reason_parts.append(f"sell_chaos_rally")
            else:
                self._cascade_detected = False
                return None

        if not side:
            self._cascade_detected = False
            return None

        # Size based on cascade magnitude
        vol_scale = min(self._cascade_volume_mult / 3.0, 2.0)  # Scale up for bigger cascades
        size_pct = self.base_size_pct * vol_scale
        size_pct = min(size_pct, self.max_size_pct)
        size_usd = equity * size_pct
        size = size_usd / mid if mid > 0 else 0

        if size <= 0:
            self._cascade_detected = False
            return None

        reason = (
            f"LIQ_SWEEP {side.upper()}: {' | '.join(reason_parts)} | "
            f"cascade={self._cascade_type} vol={self._cascade_volume_mult:.1f}x "
            f"wick={self._cascade_wick_pct:.0f}% size=${size_usd:.0f} ({size_pct*100:.0f}%)"
        )

        # Set up trade tracking
        self._entry_price = mid
        self._entry_side = side
        self._peak_since_entry = mid
        self._trough_since_entry = mid
        self._candles_in_trade = 0
        self._trailing_active = False
        self._cascade_detected = False

        return StrategyDecision(
            action="place_order",
            side=side,
            size=size,
            price=mid,
            reason=reason,
        )

    def _reset_trade_state(self):
        """Clean up after closing a trade."""
        self._in_trade = False
        self._entry_price = 0.0
        self._entry_side = ""
        self._peak_since_entry = 0.0
        self._trough_since_entry = float('inf')
        self._candles_in_trade = 0
        self._trailing_active = False
