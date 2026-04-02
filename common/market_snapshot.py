"""MarketSnapshot — pre-digested market structure for AI consumption.

Inspired by Claude Code's context architecture: code does the heavy lifting
so the model gets compact, pre-computed data instead of raw arrays.

Usage:
    from common.market_snapshot import build_snapshot, render_snapshot
    from modules.candle_cache import CandleCache

    cache = CandleCache()
    snap = build_snapshot("BTC", cache, current_price=84500.0)
    text = render_snapshot(snap)  # compact text block for AI prompt

The text output is designed to be token-efficient:
- No raw candle arrays (saves 80%+ tokens vs dumping OHLCV)
- Pre-computed levels with distance from current price
- Actionable labels ("squeeze", "overbought", "bullish_div")
- Hierarchical: summary line first, details only if needed

Integration points:
- Thesis writer (scheduled task): include render_snapshot() in the prompt
- TickContext: attach MarketSnapshot per market for execution decisions
- Autoresearch iterator: use snapshot to decide when to trigger research
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from common.market_structure import (
    OHLCV,
    BollingerBands,
    KeyLevel,
    TrendAnalysis,
    VolumeProfile,
    VolumeWeightedMomentum,
    VolatilityRegime,
    atr,
    bollinger_bands,
    find_key_levels,
    trend_analysis,
    volume_profile,
    volume_weighted_momentum,
    volatility_regime,
    vwap,
)

log = logging.getLogger("market_snapshot")


@dataclass
class TimeframeData:
    """Pre-computed indicators for one timeframe."""
    interval: str           # "1h", "4h", "1d"
    candle_count: int
    trend: TrendAnalysis
    bb: Optional[BollingerBands]
    atr_value: float
    atr_pct: float          # ATR as % of price — normalized volatility
    vwap_value: float
    vol_profile: Optional[VolumeProfile]
    price_change_pct: float  # % change over the candle window
    vwm: Optional[VolumeWeightedMomentum] = None    # volume-weighted momentum
    vol_regime: Optional[VolatilityRegime] = None    # volatility regime classification


@dataclass
class MarketSnapshot:
    """Complete pre-digested market structure for one instrument.

    This is the contract between code (producer) and AI (consumer).
    Every field is pre-computed — the AI never touches raw candles.
    """
    market: str
    current_price: float
    timestamp: int          # when snapshot was computed

    # Multi-timeframe analysis
    timeframes: Dict[str, TimeframeData] = field(default_factory=dict)

    # Aggregated key levels (from all timeframes + volume + round numbers)
    key_levels: List[KeyLevel] = field(default_factory=list)

    # Quick-scan flags — the AI reads these first
    flags: List[str] = field(default_factory=list)
    # e.g. ["bb_squeeze_4h", "rsi_oversold_1h", "bullish_div_4h",
    #        "above_vwap", "volume_surge", "near_support"]

    # Suggested mechanical levels (code-computed, AI can override)
    suggested_stop: Optional[float] = None
    suggested_tp: Optional[float] = None
    suggested_entry: Optional[float] = None


def build_snapshot(
    market: str,
    candle_source,  # CandleCache or anything with .get_candles(coin, interval, start_ms, end_ms)
    current_price: float,
    intervals: Optional[List[str]] = None,
    lookback_days: int = 30,
) -> MarketSnapshot:
    """Build a complete MarketSnapshot from cached candle data.

    Args:
        market: Market identifier (e.g. "BTC", "xyz:BRENTOIL")
        candle_source: Object with .get_candles(coin, interval, start_ms, end_ms)
        current_price: Live price from connector
        intervals: Which timeframes to analyze (default: ["1h", "4h", "1d"])
        lookback_days: How far back to pull candles

    Returns:
        MarketSnapshot with all indicators pre-computed.
    """
    if intervals is None:
        intervals = ["1h", "4h", "1d"]

    now_ms = int(time.time() * 1000)
    start_ms = now_ms - (lookback_days * 86_400_000)

    snap = MarketSnapshot(
        market=market,
        current_price=current_price,
        timestamp=now_ms,
    )

    all_candles_for_levels: List[OHLCV] = []

    for interval in intervals:
        raw = candle_source.get_candles(market, interval, start_ms, now_ms)
        if not raw:
            log.debug("No %s candles for %s — skipping timeframe", interval, market)
            continue

        candles = OHLCV.from_hl_list(raw)
        closes = [c.c for c in candles]

        if not closes:
            continue

        # Compute all indicators
        ta = trend_analysis(candles)
        bb = bollinger_bands(closes, current_price=current_price)
        atr_val = atr(candles)
        atr_pct = (atr_val / current_price * 100) if current_price > 0 else 0
        vwap_val = vwap(candles[-24:] if len(candles) > 24 else candles)  # rolling 24 bars
        vp = volume_profile(candles)
        price_change = (closes[-1] - closes[0]) / closes[0] * 100 if closes[0] > 0 else 0

        # Quant signals (v3)
        vwm = volume_weighted_momentum(candles) if len(candles) > 20 else None
        vol_reg = volatility_regime(candles, current_price) if len(candles) > 20 else None

        tf_data = TimeframeData(
            interval=interval,
            candle_count=len(candles),
            trend=ta,
            bb=bb,
            atr_value=atr_val,
            atr_pct=round(atr_pct, 3),
            vwap_value=vwap_val,
            vol_profile=vp,
            vwm=vwm,
            vol_regime=vol_reg,
            price_change_pct=round(price_change, 2),
        )
        snap.timeframes[interval] = tf_data

        # Collect candles for level detection (prefer 4h for levels)
        if interval == "4h" or not all_candles_for_levels:
            all_candles_for_levels = candles

        # Generate flags from this timeframe
        _generate_flags(snap, tf_data, current_price)

    # Aggregate key levels across all sources
    if all_candles_for_levels:
        best_bb = None
        best_vp = None
        for tf in snap.timeframes.values():
            if tf.interval == "4h":
                best_bb = tf.bb
                best_vp = tf.vol_profile
                break
            if best_bb is None:
                best_bb = tf.bb
                best_vp = tf.vol_profile

        snap.key_levels = find_key_levels(
            all_candles_for_levels,
            current_price,
            bb=best_bb,
            vp=best_vp,
        )

    # Compute suggested mechanical levels
    _compute_suggested_levels(snap)

    return snap


def build_snapshot_from_candles(
    market: str,
    candle_sets: Dict[str, List[Dict]],
    current_price: float,
) -> MarketSnapshot:
    """Build snapshot from pre-fetched candle dicts (no cache needed).

    Useful when candles are already in TickContext.candles.

    Args:
        market: Market identifier
        candle_sets: {"1h": [candle_dicts], "4h": [...], ...}
        current_price: Live price
    """
    snap = MarketSnapshot(
        market=market,
        current_price=current_price,
        timestamp=int(time.time() * 1000),
    )

    all_candles_for_levels: List[OHLCV] = []

    for interval, raw in candle_sets.items():
        if not raw:
            continue

        candles = OHLCV.from_hl_list(raw)
        closes = [c.c for c in candles]
        if not closes:
            continue

        ta = trend_analysis(candles)
        bb = bollinger_bands(closes, current_price=current_price)
        atr_val = atr(candles)
        atr_pct = (atr_val / current_price * 100) if current_price > 0 else 0
        vwap_val = vwap(candles[-24:] if len(candles) > 24 else candles)
        vp = volume_profile(candles)
        price_change = (closes[-1] - closes[0]) / closes[0] * 100 if closes[0] > 0 else 0

        vwm = volume_weighted_momentum(candles) if len(candles) > 20 else None
        vol_reg = volatility_regime(candles, current_price) if len(candles) > 20 else None

        tf_data = TimeframeData(
            interval=interval,
            candle_count=len(candles),
            trend=ta,
            bb=bb,
            atr_value=atr_val,
            atr_pct=round(atr_pct, 3),
            vwap_value=vwap_val,
            vol_profile=vp,
            price_change_pct=round(price_change, 2),
            vwm=vwm,
            vol_regime=vol_reg,
        )
        snap.timeframes[interval] = tf_data

        if interval == "4h" or not all_candles_for_levels:
            all_candles_for_levels = candles

        _generate_flags(snap, tf_data, current_price)

    if all_candles_for_levels:
        best_bb = None
        best_vp = None
        for tf in snap.timeframes.values():
            if tf.interval == "4h":
                best_bb = tf.bb
                best_vp = tf.vol_profile
                break
            if best_bb is None:
                best_bb = tf.bb
                best_vp = tf.vol_profile

        snap.key_levels = find_key_levels(
            all_candles_for_levels, current_price, bb=best_bb, vp=best_vp,
        )

    _compute_suggested_levels(snap)
    return snap


# ═══════════════════════════════════════════════════════════════════════════════
# Text renderer — the token-efficient output the AI actually reads
# ═══════════════════════════════════════════════════════════════════════════════

def render_snapshot(snap: MarketSnapshot, detail: str = "standard") -> str:
    """Render MarketSnapshot as compact text for AI prompt injection.

    Detail levels (inspired by Claude Code's tiered context):
      - "brief": ~100 tokens — flags + key levels only
      - "standard": ~250 tokens — adds per-timeframe trend/BB/ATR
      - "full": ~400 tokens — adds volume profile, patterns, suggestions

    Compare: raw 200 candles ≈ 4,000+ tokens. This is 10-20x compression.
    """
    lines = []

    # Header
    lines.append(f"=== {snap.market} @ {snap.current_price:.4g} ===")

    # Flags (always included — cheapest signal)
    if snap.flags:
        lines.append(f"FLAGS: {', '.join(snap.flags)}")

    # Key levels (always included)
    if snap.key_levels:
        supports = [kl for kl in snap.key_levels if kl.type == "support"]
        resists = [kl for kl in snap.key_levels if kl.type == "resistance"]
        if supports:
            s_str = ", ".join(f"{kl.price:.4g}({kl.source}/{kl.strength}t/{kl.distance_pct:+.1f}%)" for kl in supports[:4])
            lines.append(f"SUPPORT: {s_str}")
        if resists:
            r_str = ", ".join(f"{kl.price:.4g}({kl.source}/{kl.strength}t/{kl.distance_pct:+.1f}%)" for kl in resists[:4])
            lines.append(f"RESIST: {r_str}")

    if detail == "brief":
        if snap.suggested_stop or snap.suggested_tp:
            lines.append(f"MECH: SL={_fmt(snap.suggested_stop)} TP={_fmt(snap.suggested_tp)} entry={_fmt(snap.suggested_entry)}")
        return "\n".join(lines)

    # Per-timeframe data
    for interval in ["1d", "4h", "1h"]:
        tf = snap.timeframes.get(interval)
        if not tf:
            continue

        t = tf.trend
        parts = [
            f"{interval}: {t.direction}({t.strength})",
            f"RSI={t.rsi:.0f}",
            f"EMA={t.ema_spread_pct:+.2f}%",
            f"ATR={tf.atr_value:.4g}({tf.atr_pct:.1f}%)",
        ]

        if tf.bb:
            parts.append(f"BB={tf.bb.zone}")
            if tf.bb.is_squeeze:
                parts.append("SQUEEZE")

        if t.rsi_divergence != "none":
            parts.append(t.rsi_divergence)

        if t.candle_patterns:
            parts.append(f"patterns=[{','.join(t.candle_patterns)}]")

        parts.append(f"chg={tf.price_change_pct:+.1f}%")

        # Quant v3 additions
        if tf.vwm and tf.vwm.vol_price_accel != "neutral":
            parts.append(f"flow={tf.vwm.vol_price_accel}({tf.vwm.obv_trend})")
        if tf.vol_regime and tf.vol_regime.regime != "normal":
            parts.append(f"vol_regime={tf.vol_regime.regime}({tf.vol_regime.percentile:.0f}%ile)")

        lines.append(" | ".join(parts))

    if detail == "standard":
        if snap.suggested_stop or snap.suggested_tp:
            lines.append(f"MECH: SL={_fmt(snap.suggested_stop)} TP={_fmt(snap.suggested_tp)} entry={_fmt(snap.suggested_entry)}")
        return "\n".join(lines)

    # Full detail: volume profile
    for interval in ["4h", "1d"]:
        tf = snap.timeframes.get(interval)
        if tf and tf.vol_profile:
            vp = tf.vol_profile
            lines.append(
                f"VPOC({interval}): {vp.poc:.4g} | "
                f"VA: {vp.value_area_low:.4g}-{vp.value_area_high:.4g} "
                f"({vp.value_area_width_pct:.1f}% wide)"
            )

    # Suggested levels
    if snap.suggested_stop or snap.suggested_tp:
        lines.append(
            f"MECHANICAL: stop={_fmt(snap.suggested_stop)} "
            f"tp={_fmt(snap.suggested_tp)} entry={_fmt(snap.suggested_entry)}"
        )

    return "\n".join(lines)


def render_signal_summary(snap: MarketSnapshot, position: Optional[Dict] = None) -> str:
    """Pre-computed plain-English signal assessment.

    This is THE key function for making dumb models useful. Instead of
    giving the model raw flags/numbers and hoping it interprets correctly,
    we do the interpretation here and give it sentences to quote.

    IMPORTANT: The model should QUOTE this output, not reinterpret it.
    Reinterpretation causes directional errors (e.g. saying "exhaustion
    may give a bounce" when exhaustion means the rally drops).

    Args:
        snap: MarketSnapshot with pre-computed indicators
        position: Optional dict with 'direction' ('long'/'short') and 'size'
                  to add position-specific guidance

    Returns ~150 tokens of actionable analysis covering:
    - Overall bias (bullish/bearish/neutral)
    - Exhaustion/momentum signals
    - Key risk levels
    - Position guidance for longs AND shorts
    - Position-specific impact if position provided
    """
    signals = []
    bias_score = 0  # positive = bullish, negative = bearish

    # Gather data from primary timeframe (prefer 1h for short-term signals)
    tf_1h = snap.timeframes.get("1h")
    tf_4h = snap.timeframes.get("4h")
    tf_1d = snap.timeframes.get("1d")
    primary = tf_1h or tf_4h

    if not primary:
        return "SIGNAL: Insufficient data for analysis."

    rsi = primary.trend.rsi
    direction = primary.trend.direction
    strength = primary.trend.strength
    patterns = primary.trend.candle_patterns
    bb_zone = primary.bb.zone if primary.bb else "mid"
    bb_squeeze = primary.bb.is_squeeze if primary.bb else False
    ema_spread = primary.trend.ema_spread_pct
    price_change = primary.price_change_pct
    divergence = primary.trend.rsi_divergence

    # ── Trend assessment ──
    if direction == "up" and strength > 50:
        bias_score += 2
    elif direction == "up":
        bias_score += 1
    elif direction == "down" and strength > 50:
        bias_score -= 2
    elif direction == "down":
        bias_score -= 1

    # ── Multi-timeframe confluence ──
    tf_directions = []
    for label, tf in [("1h", tf_1h), ("4h", tf_4h), ("1d", tf_1d)]:
        if tf:
            tf_directions.append((label, tf.trend.direction, tf.trend.strength))
    all_up = all(d == "up" for _, d, _ in tf_directions)
    all_down = all(d == "down" for _, d, _ in tf_directions)
    if all_up:
        signals.append("All timeframes aligned bullish")
        bias_score += 1
    elif all_down:
        signals.append("All timeframes aligned bearish")
        bias_score -= 1
    elif len(tf_directions) > 1:
        dirs = ", ".join(f"{l}={d}" for l, d, _ in tf_directions)
        signals.append(f"Mixed trend ({dirs})")

    # ── Exhaustion detection (KEY for dumb models) ──
    exhaustion_bull = (rsi > 65 and bb_zone == "above_upper")
    exhaustion_bear = (rsi < 35 and bb_zone == "below_lower")
    reversal_candle = any(p in patterns for p in ["doji", "hammer", "shooting_star", "engulfing"])

    if exhaustion_bull and reversal_candle:
        signals.append(f"EXHAUSTION — RSI {rsi:.0f} + above upper BB + {', '.join(patterns)}. Pullback likely")
        bias_score -= 2
    elif exhaustion_bull:
        signals.append(f"Overbought zone — RSI {rsi:.0f}, above upper BB. Watch for reversal")
        bias_score -= 1
    elif exhaustion_bear and reversal_candle:
        signals.append(f"CAPITULATION — RSI {rsi:.0f} + below lower BB + {', '.join(patterns)}. Bounce likely")
        bias_score += 2
    elif exhaustion_bear:
        signals.append(f"Oversold zone — RSI {rsi:.0f}, below lower BB. Watch for bounce")
        bias_score += 1
    elif rsi > 70:
        signals.append(f"RSI overbought ({rsi:.0f})")
        bias_score -= 1
    elif rsi < 30:
        signals.append(f"RSI oversold ({rsi:.0f})")
        bias_score += 1

    # ── Divergence ──
    if divergence == "bullish_div":
        signals.append("Bullish RSI divergence — price falling but momentum rising")
        bias_score += 2
    elif divergence == "bearish_div":
        signals.append("Bearish RSI divergence — price rising but momentum fading")
        bias_score -= 2

    # ── BB Squeeze ──
    if bb_squeeze:
        signals.append("BB squeeze — volatility compressed, breakout imminent")

    # ── Momentum ──
    if abs(price_change) > 10:
        direction_word = "rally" if price_change > 0 else "selloff"
        signals.append(f"Strong {direction_word} ({price_change:+.1f}% over window)")
    elif abs(ema_spread) > 3:
        signals.append(f"Momentum {'bullish' if ema_spread > 0 else 'bearish'} (EMA spread {ema_spread:+.1f}%)")

    # ── Key levels ──
    nearest_support = None
    nearest_resist = None
    for kl in snap.key_levels:
        if kl.type == "support" and (nearest_support is None or abs(kl.distance_pct) < abs(nearest_support.distance_pct)):
            nearest_support = kl
        if kl.type == "resistance" and (nearest_resist is None or abs(kl.distance_pct) < abs(nearest_resist.distance_pct)):
            nearest_resist = kl

    level_note = ""
    if nearest_support and abs(nearest_support.distance_pct) < 2:
        level_note = f"Near support ${nearest_support.price:.4g} ({nearest_support.distance_pct:+.1f}%)"
        bias_score += 1
    if nearest_resist and abs(nearest_resist.distance_pct) < 2:
        r_note = f"Near resistance ${nearest_resist.price:.4g} ({nearest_resist.distance_pct:+.1f}%)"
        level_note = f"{level_note}. {r_note}" if level_note else r_note
        bias_score -= 1
    if level_note:
        signals.append(level_note)

    # ── Compose summary ──
    if bias_score >= 3:
        overall = "STRONGLY BULLISH"
        emoji = "🟢🟢"
    elif bias_score >= 1:
        overall = "BULLISH"
        emoji = "🟢"
    elif bias_score <= -3:
        overall = "STRONGLY BEARISH"
        emoji = "🔴🔴"
    elif bias_score <= -1:
        overall = "BEARISH"
        emoji = "🔴"
    else:
        overall = "NEUTRAL"
        emoji = "⚪"

    lines = [f"SIGNAL: {emoji} {overall} (score: {bias_score:+d})"]
    for s in signals:
        lines.append(f"  • {s}")

    # ── Volume-weighted momentum (quant v3) ──
    if primary.vwm:
        vwm = primary.vwm
        if vwm.vol_price_accel in ("strong_buy", "strong_sell"):
            vol_label = "STRONG" if vwm.recent_vs_avg > 1.5 else "elevated"
            if vwm.vol_price_accel == "strong_buy":
                lines.append(f"  • Money flow: {vol_label} accumulation (OBV {vwm.obv_trend}, vol {vwm.recent_vs_avg:.1f}x avg)")
                bias_score += 1
            else:
                lines.append(f"  • Money flow: {vol_label} distribution (OBV {vwm.obv_trend}, vol {vwm.recent_vs_avg:.1f}x avg)")
                bias_score -= 1
        elif vwm.obv_trend == "accumulating" and direction == "up":
            lines.append(f"  • Volume confirms trend (OBV accumulating, {vwm.recent_vs_avg:.1f}x avg vol)")
        elif vwm.obv_trend == "distributing" and direction == "up":
            lines.append(f"  • ⚠️ Volume divergence: price rising but OBV distributing (smart money exiting?)")
            bias_score -= 1
        elif vwm.obv_trend == "accumulating" and direction == "down":
            lines.append(f"  • ⚠️ Volume divergence: price falling but OBV accumulating (smart money buying?)")
            bias_score += 1

    # ── Volatility regime (quant v3) ──
    if primary.vol_regime:
        vr = primary.vol_regime
        if vr.regime == "extreme":
            lines.append(f"  • 🔥 EXTREME volatility ({vr.percentile:.0f}th percentile) — reduce size, widen stops")
        elif vr.regime == "low":
            lines.append(f"  • 💤 LOW volatility ({vr.percentile:.0f}th percentile) — compression before breakout?")

    # Position guidance — explicit about WHAT HAPPENS TO PRICE
    # (models get confused about "exhaustion helps shorts" so spell it out)
    bb_mid = primary.bb.middle if primary.bb else None
    mid_str = f" toward ${bb_mid:.4g} (BB mid)" if bb_mid else ""

    if exhaustion_bull:
        lines.append(f"  → PRICE OUTLOOK: Rally exhausted, expect pullback/drop{mid_str}")
        lines.append("  → SHORTS benefit from the drop. LONGS should wait for pullback to enter.")
    elif exhaustion_bear:
        lines.append(f"  → PRICE OUTLOOK: Selling exhausted, expect bounce/recovery{mid_str}")
        lines.append("  → LONGS benefit from the bounce. SHORTS should cover/take profits.")
    elif bias_score >= 2:
        lines.append("  → PRICE OUTLOOK: Upward pressure. LONGS favorable. SHORTS high risk.")
    elif bias_score <= -2:
        lines.append("  → PRICE OUTLOOK: Downward pressure. SHORTS favorable. LONGS high risk.")
    else:
        lines.append("  → PRICE OUTLOOK: No clear direction. Wait for signal before committing.")

    # Position-specific impact (when position data is available)
    if position:
        pos_dir = position.get("direction", "").lower()
        pos_size = position.get("size", 0)
        if pos_dir in ("long", "short"):
            # Determine if signal helps or hurts the position
            if pos_dir == "long":
                favorable = bias_score > 0 or exhaustion_bear
                harmful = bias_score < -1 or exhaustion_bull
            else:  # short
                favorable = bias_score < 0 or exhaustion_bull
                harmful = bias_score > 1 or exhaustion_bear

            if favorable:
                lines.append(f"  ✅ YOUR {pos_dir.upper()}: Signal SUPPORTS your position")
            elif harmful:
                lines.append(f"  ⚠️ YOUR {pos_dir.upper()}: Signal is AGAINST your position")
            else:
                lines.append(f"  ➡️ YOUR {pos_dir.upper()}: Signal is neutral for your position")

    # Volatility context
    vol_pct = primary.atr_pct
    if vol_pct > 3:
        lines.append(f"  ⚡ HIGH volatility (ATR {vol_pct:.1f}%) — size conservatively")
    elif vol_pct < 0.5:
        lines.append(f"  💤 LOW volatility (ATR {vol_pct:.1f}%) — breakout setup possible")

    return "\n".join(lines)


def snapshot_to_dict(snap: MarketSnapshot) -> Dict:
    """Serialize snapshot to JSON-safe dict for storage/API."""
    return {
        "market": snap.market,
        "current_price": snap.current_price,
        "timestamp": snap.timestamp,
        "flags": snap.flags,
        "key_levels": [
            {
                "price": kl.price,
                "type": kl.type,
                "strength": kl.strength,
                "source": kl.source,
                "distance_pct": kl.distance_pct,
            }
            for kl in snap.key_levels
        ],
        "timeframes": {
            interval: {
                "interval": tf.interval,
                "candle_count": tf.candle_count,
                "trend_direction": tf.trend.direction,
                "trend_strength": tf.trend.strength,
                "rsi": tf.trend.rsi,
                "ema_spread_pct": tf.trend.ema_spread_pct,
                "rsi_divergence": tf.trend.rsi_divergence,
                "higher_highs": tf.trend.higher_highs,
                "higher_lows": tf.trend.higher_lows,
                "candle_patterns": tf.trend.candle_patterns,
                "bb_zone": tf.bb.zone if tf.bb else None,
                "bb_squeeze": tf.bb.is_squeeze if tf.bb else None,
                "bb_bandwidth": tf.bb.bandwidth if tf.bb else None,
                "bb_pct_b": tf.bb.pct_b if tf.bb else None,
                "atr": tf.atr_value,
                "atr_pct": tf.atr_pct,
                "vwap": tf.vwap_value,
                "price_change_pct": tf.price_change_pct,
                "vpoc": tf.vol_profile.poc if tf.vol_profile else None,
                "va_low": tf.vol_profile.value_area_low if tf.vol_profile else None,
                "va_high": tf.vol_profile.value_area_high if tf.vol_profile else None,
            }
            for interval, tf in snap.timeframes.items()
        },
        "suggested_stop": snap.suggested_stop,
        "suggested_tp": snap.suggested_tp,
        "suggested_entry": snap.suggested_entry,
    }


# ═══════════════════════════════════════════════════════════════════════════════
# Internal helpers
# ═══════════════════════════════════════════════════════════════════════════════

def _generate_flags(snap: MarketSnapshot, tf: TimeframeData, price: float) -> None:
    """Add quick-scan flags based on indicator thresholds."""
    sfx = f"_{tf.interval}"

    # Bollinger squeeze
    if tf.bb and tf.bb.is_squeeze:
        snap.flags.append(f"bb_squeeze{sfx}")

    # Overbought / oversold
    if tf.trend.rsi > 70:
        snap.flags.append(f"rsi_overbought{sfx}")
    elif tf.trend.rsi < 30:
        snap.flags.append(f"rsi_oversold{sfx}")

    # RSI divergence
    if tf.trend.rsi_divergence != "none":
        snap.flags.append(f"{tf.trend.rsi_divergence}{sfx}")

    # Price vs VWAP
    if tf.vwap_value > 0 and price > 0:
        vwap_dist = (price - tf.vwap_value) / tf.vwap_value * 100
        if vwap_dist > 2:
            snap.flags.append(f"above_vwap{sfx}")
        elif vwap_dist < -2:
            snap.flags.append(f"below_vwap{sfx}")

    # Trend extremes
    if tf.trend.strength > 70:
        snap.flags.append(f"strong_trend{sfx}")

    # Volatility extremes
    if tf.atr_pct > 5:
        snap.flags.append(f"high_vol{sfx}")
    elif tf.atr_pct < 1:
        snap.flags.append(f"low_vol{sfx}")

    # Near key level detection
    if snap.key_levels:
        for kl in snap.key_levels:
            if abs(kl.distance_pct) < 1.0:
                snap.flags.append(f"near_{kl.type}")
                break  # only flag once


def _compute_suggested_levels(snap: MarketSnapshot) -> None:
    """Compute mechanical entry/stop/TP from indicators.

    These are suggestions — the AI can override with thesis-based levels.
    """
    # Use 4h ATR for stops, fall back to 1h
    atr_val = 0.0
    for interval in ["4h", "1h", "1d"]:
        tf = snap.timeframes.get(interval)
        if tf and tf.atr_value > 0:
            atr_val = tf.atr_value
            break

    if atr_val > 0 and snap.current_price > 0:
        # Stop: 3x ATR below current price (long bias)
        snap.suggested_stop = round(snap.current_price - 3 * atr_val, 6)
        # TP: 5x ATR above (reward:risk ≈ 1.67)
        snap.suggested_tp = round(snap.current_price + 5 * atr_val, 6)

    # Entry: nearest strong support or VWAP, whichever is closer
    supports = [kl for kl in snap.key_levels if kl.type == "support" and kl.distance_pct > 0]
    if supports:
        snap.suggested_entry = supports[0].price
    else:
        # Fall back to VWAP if it's below price
        for tf in snap.timeframes.values():
            if tf.vwap_value > 0 and tf.vwap_value < snap.current_price:
                snap.suggested_entry = round(tf.vwap_value, 6)
                break


def _fmt(val: Optional[float]) -> str:
    """Format a price value or return '-' if None."""
    if val is None:
        return "-"
    return f"{val:.4g}"
