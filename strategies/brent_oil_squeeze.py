"""Brent Oil Supply Squeeze strategy — geopolitical-thesis + trend-following hybrid.

Thesis: Major supply disruption from Middle East conflict (Strait of Hormuz blockade,
damaged infrastructure in UAE/Bahrain/Qatar/Oman, Russian pipeline damage from Ukraine).
Production restarts take months. Escalation risk is asymmetric upward.

Strategy design:
  - STRONG LONG BIAS: Only takes long positions. This is a directional conviction trade.
  - Trend confirmation: EMA 9/21 crossover + price above 50-EMA = bullish structure intact.
  - Dip buying: When price pulls back to 21-EMA or 50-EMA support, scale into longs.
  - Momentum filter: RSI > 40 required (avoid catching a falling knife in panic sell-offs).
  - Volatility sizing: ATR-based position sizing — bigger when vol is low (quiet accumulation),
    smaller when vol spikes (news-driven chaos = wider stops needed).
  - Trailing stop: ATR-based, only exits on trend breakdown — not trying to scalp.
  - NO SHORTS: In a supply squeeze, shorting is picking up pennies in front of a bulldozer.

Risk management:
  - Max position: capped by leverage and account equity
  - Stop loss: 3x ATR below entry (gives room for volatility without getting stopped)
  - Take profit: none — let winners run in a squeeze, trailing stop handles exit
  - Re-entry: after stop-out, wait for trend to re-establish (EMA realignment)

Designed for: BRENTOIL-USDC on Hyperliquid (xyz:BRENTOIL)
Interval: 1h recommended (captures intraday momentum without noise)
"""
from __future__ import annotations

import math
from collections import deque
from typing import List, Optional

from common.models import MarketSnapshot, StrategyDecision
from common.position_risk import (
    DipAddGateConfig,
    PositionSnapshot,
    evaluate_dip_add_gate,
)
from sdk.strategy_sdk.base import BaseStrategy, StrategyContext

# --- Configurable parameters ---
EMA_FAST = 9         # Fast signal line
EMA_MID = 21         # Primary trend
EMA_SLOW = 50        # Major support/resistance
RSI_PERIOD = 14      # Momentum filter
RSI_FLOOR = 40       # Don't buy below this (trend broken)
RSI_OVERBOUGHT = 82  # Reduce aggression above this (let it breathe)
ATR_PERIOD = 24      # Volatility measurement (24h of 1h candles)
ATR_STOP_MULT = 3.0  # Stop distance: 3x ATR below entry
ATR_TRAIL_MULT = 2.5 # Trailing stop: 2.5x ATR from peak
DIP_THRESHOLD_ATR = 0.8  # Buy dip when price is within 0.8 ATR of 21-EMA or 50-EMA
MIN_HISTORY = EMA_SLOW + 10  # Need enough data before trading

# Position sizing
BASE_SIZE_PCT = 0.15     # 15% of equity per entry
MAX_POSITION_PCT = 0.50  # Max 50% of equity in position (with leverage)
SCALE_IN_LEVELS = 3      # Up to 3 entries to build full position


def _ema(values: list, span: int) -> float:
    """Compute latest EMA value from a list of prices."""
    if not values:
        return 0.0
    alpha = 2.0 / (span + 1)
    ema = values[0]
    for v in values[1:]:
        ema = alpha * v + (1 - alpha) * ema
    return ema


def _rsi(closes: list, period: int) -> float:
    """Compute RSI from a list of closes."""
    if len(closes) < period + 1:
        return 50.0  # neutral

    gains = []
    losses = []
    for i in range(1, len(closes)):
        delta = closes[i] - closes[i - 1]
        gains.append(max(delta, 0))
        losses.append(max(-delta, 0))

    if len(gains) < period:
        return 50.0

    # Wilder's smoothed RS
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period

    for i in range(period, len(gains)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period

    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))


def _atr(highs: list, lows: list, closes: list, period: int) -> float:
    """Compute ATR (Average True Range)."""
    if len(closes) < 2:
        return 0.0

    true_ranges = []
    for i in range(1, len(closes)):
        tr = max(
            highs[i] - lows[i],
            abs(highs[i] - closes[i - 1]),
            abs(lows[i] - closes[i - 1]),
        )
        true_ranges.append(tr)

    if len(true_ranges) < period:
        return sum(true_ranges) / len(true_ranges) if true_ranges else 0.0

    # Wilder's smoothing
    atr = sum(true_ranges[:period]) / period
    for tr in true_ranges[period:]:
        atr = (atr * (period - 1) + tr) / period

    return atr


class BrentOilSqueezeStrategy(BaseStrategy):
    """Long-only supply squeeze strategy for Brent Oil.

    Only buys. Never shorts. Designed for sustained uptrend with
    geopolitical supply disruption as the fundamental driver.
    """

    def __init__(
        self,
        strategy_id: str = "brent_oil_squeeze",
        base_size_pct: float = BASE_SIZE_PCT,
        max_position_pct: float = MAX_POSITION_PCT,
    ):
        super().__init__(strategy_id=strategy_id)
        self.base_size_pct = base_size_pct
        self.max_position_pct = max_position_pct

        # Price history — all same maxlen so indices align
        _maxlen = EMA_SLOW + RSI_PERIOD + ATR_PERIOD + 20
        self.closes: deque = deque(maxlen=_maxlen)
        self.highs: deque = deque(maxlen=_maxlen)
        self.lows: deque = deque(maxlen=_maxlen)

        # Position tracking
        self._entry_price: float = 0.0
        self._peak_price: float = 0.0
        self._num_entries: int = 0
        self._stopped_out: bool = False
        self._cooldown_ticks: int = 0

    def on_tick(
        self,
        snapshot: MarketSnapshot,
        context: Optional[StrategyContext] = None,
    ) -> List[StrategyDecision]:
        mid = snapshot.mid_price
        if mid <= 0:
            return []

        high = snapshot.ask if snapshot.ask > 0 else mid
        low = snapshot.bid if snapshot.bid > 0 else mid

        self.closes.append(mid)
        self.highs.append(high)
        self.lows.append(low)

        # Need enough history
        if len(self.closes) < MIN_HISTORY:
            return []

        # Cooldown after stop-out (wait for trend to re-establish)
        if self._cooldown_ticks > 0:
            self._cooldown_ticks -= 1
            return []

        # --- Compute indicators ---
        closes = list(self.closes)
        highs = list(self.highs)
        lows = list(self.lows)

        ema_fast = _ema(closes, EMA_FAST)
        ema_mid = _ema(closes, EMA_MID)
        ema_slow = _ema(closes, EMA_SLOW)
        rsi = _rsi(closes, RSI_PERIOD)
        atr = _atr(highs, lows, closes, ATR_PERIOD)

        if atr <= 0:
            return []

        # --- Position state from context ---
        in_position = False
        position_size = 0.0
        equity = 10_000.0  # default

        if context:
            position_size = abs(context.position_qty)
            # Positive qty = long, negative = short
            in_position = context.position_qty > 0
            equity = context.meta.get("account_value", 10_000.0)
            if context.position_notional > 0 and equity == 10_000.0:
                equity = context.position_notional + 10_000.0  # rough estimate

        decisions = []

        # ========================================
        # EXIT LOGIC — check stops first
        # ========================================
        if in_position:
            # Update peak for trailing stop
            if mid > self._peak_price:
                self._peak_price = mid

            # Hard stop: 3x ATR below entry
            hard_stop = self._entry_price - (ATR_STOP_MULT * atr)
            # Trailing stop: 2.5x ATR below peak
            trail_stop = self._peak_price - (ATR_TRAIL_MULT * atr)
            # Use the higher of the two (tighter stop as profit builds)
            stop_price = max(hard_stop, trail_stop)

            # Trend breakdown exit: price below 50-EMA AND fast EMA below mid EMA
            trend_broken = mid < ema_slow and ema_fast < ema_mid

            if mid <= stop_price or trend_broken:
                reason = "trailing_stop" if mid <= stop_price else "trend_breakdown"
                decisions.append(StrategyDecision(
                    action="place_order",
                    side="short",  # closing a long
                    size=position_size,
                    price=mid,
                    reason=f"EXIT: {reason} | price={mid:.2f} stop={stop_price:.2f} "
                           f"peak={self._peak_price:.2f} atr={atr:.2f}",
                ))
                self._entry_price = 0.0
                self._peak_price = 0.0
                self._num_entries = 0
                self._stopped_out = True
                self._cooldown_ticks = 6  # wait 6 ticks before re-entry
                return decisions

        # ========================================
        # ENTRY LOGIC — long only
        # ========================================

        # Bullish structure check
        bullish_emas = ema_fast > ema_mid  # fast above mid = uptrend
        above_support = mid > ema_slow     # price above major support
        rsi_ok = rsi > RSI_FLOOR           # not in free-fall
        not_overextended = rsi < RSI_OVERBOUGHT  # room to run

        # Max position check
        max_notional = equity * self.max_position_pct
        current_notional = position_size * mid if in_position else 0.0
        room_to_add = current_notional < max_notional

        if not room_to_add:
            return decisions  # position is full

        if not rsi_ok:
            return decisions  # momentum too weak

        should_enter = False
        entry_reason = ""
        is_dip_signal = False  # Track if this is a dip-add vs fresh entry

        # Signal 1: EMA crossover (fresh trend confirmation — only when NOT in position)
        if bullish_emas and above_support and not_overextended and not in_position:
            should_enter = True
            is_dip_signal = False
            entry_reason = f"ema_cross_bullish | ema9={ema_fast:.2f} > ema21={ema_mid:.2f} > ema50={ema_slow:.2f}"

        # Signal 2: Dip buy — price pulls back near 21-EMA support while trend intact
        if ema_fast > ema_mid and mid > ema_slow:
            dist_to_mid_ema = abs(mid - ema_mid)
            if dist_to_mid_ema < DIP_THRESHOLD_ATR * atr and mid >= ema_mid * 0.995:
                should_enter = True
                is_dip_signal = True
                entry_reason = f"dip_buy_21ema | dist={dist_to_mid_ema:.2f} < {DIP_THRESHOLD_ATR * atr:.2f}"

        # Signal 3: Deep dip to 50-EMA — strong support bounce
        if mid > ema_slow and abs(mid - ema_slow) < DIP_THRESHOLD_ATR * atr:
            if rsi > 45:  # slightly higher RSI floor for deep dips
                should_enter = True
                is_dip_signal = True
                entry_reason = f"dip_buy_50ema | near major support ema50={ema_slow:.2f}"

        # Signal 4: Strong momentum — RSI rising from 50s, all EMAs aligned
        if bullish_emas and above_support and 55 < rsi < 72:
            if ema_fast > ema_mid > ema_slow:  # perfect alignment
                should_enter = True
                is_dip_signal = in_position  # Only a dip-add if we're already in
                entry_reason = f"momentum_aligned | ema9>ema21>ema50, rsi={rsi:.1f}"

        # ── POSITION RISK GATE — applied to all dip-adds ────────────────────
        # Fresh entries (not in position) bypass the gate.
        # Any add-to-existing-position MUST pass the gate.
        gate_result = None
        if should_enter and is_dip_signal and in_position and context:
            liq_price = context.meta.get("liquidation_price", 0.0)
            last_add_ts = context.meta.get("last_add_timestamp", 0.0)
            n_adds = context.meta.get("num_adds_this_session", self._num_entries)
            daily_dd = context.meta.get("daily_drawdown_pct", 0.0)
            cum_funding = context.meta.get("cumulative_funding_pct", 0.0)

            pos_snap = PositionSnapshot(
                symbol=snapshot.instrument,
                side="long" if context.position_qty > 0 else "short",
                position_qty=abs(context.position_qty),
                position_notional=current_notional,
                entry_price=self._entry_price,
                current_price=mid,
                liquidation_price=liq_price,
                account_equity=equity,
                margin_used=context.meta.get("margin_used", current_notional / max(context.meta.get("leverage", 5.0), 1.0)),
                num_adds_this_session=n_adds,
                last_add_timestamp=last_add_ts,
                daily_drawdown_pct=daily_dd,
                cumulative_funding_pct=cum_funding,
            )

            gate_result = evaluate_dip_add_gate(pos_snap)
            gate_result.log_it()

            if gate_result.decision.is_blocked:
                should_enter = False  # Gate blocked — skip this add

        if should_enter and self._num_entries < SCALE_IN_LEVELS:
            # ATR-adjusted sizing: smaller when volatile, bigger when calm
            vol_adj = 1.0
            typical_atr_pct = 0.015  # assume ~1.5% typical ATR for oil
            current_atr_pct = atr / mid if mid > 0 else typical_atr_pct
            if current_atr_pct > 0:
                vol_adj = min(1.5, max(0.4, typical_atr_pct / current_atr_pct))

            # Scale down subsequent entries
            scale_factor = 1.0 / (1 + self._num_entries * 0.5)

            # Apply gate-recommended size reduction (e.g. 0.5 when near liq warning zone)
            gate_scale = gate_result.recommended_size_pct if gate_result else 1.0

            size_usd = equity * self.base_size_pct * vol_adj * scale_factor * gate_scale
            size = size_usd / mid if mid > 0 else 0.0

            if size > 0:
                gate_note = f" gate={gate_result.decision.value}" if gate_result else ""
                decisions.append(StrategyDecision(
                    action="place_order",
                    side="long",
                    size=size,
                    price=mid,
                    reason=f"LONG: {entry_reason} | rsi={rsi:.1f} atr={atr:.2f} "
                           f"size={size:.4f} vol_adj={vol_adj:.2f} entry#{self._num_entries + 1}"
                           f"{gate_note}",
                ))

                if not in_position:
                    self._entry_price = mid
                    self._peak_price = mid
                else:
                    # Average entry
                    old_notional = self._entry_price * position_size
                    new_notional = mid * size
                    total_size = position_size + size
                    self._entry_price = (old_notional + new_notional) / total_size if total_size > 0 else mid

                self._num_entries += 1

        return decisions
