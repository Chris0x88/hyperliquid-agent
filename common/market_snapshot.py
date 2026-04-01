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
    atr,
    bollinger_bands,
    find_key_levels,
    trend_analysis,
    volume_profile,
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
