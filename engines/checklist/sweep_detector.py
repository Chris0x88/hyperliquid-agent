"""Sweep Risk Detector — Phase 2 sub-component.

Detects the "big bank step-up sweep" pattern Chris describes:
  - Liquidation heatmap zone within 1.5 ATR of current price
  - Funding skewing wrong way for the held direction
  - Recent liquidation cascade in same market
  - Unusual OI buildup suggesting short positioning vs longs

Score: 0=safe, 1=building (1 flag), 2=elevated (2 flags), 3=imminent (3+ flags or severe combo).

Inputs we have today (from sub-systems 1-4):
  - zones.jsonl          — liquidation heatmap zones
  - cascades.jsonl       — cascade events
  - bot_patterns.jsonl   — bot classifier output
  - funding_rate         — from ctx
  - market_price, atr    — from ctx

Inputs NOT YET available (noted as Phase 3 build items):
  - Shanghai physical/futures spread   → returns None, not scored
  - CFTC COT positioning data feed     → returns None, not scored
  - Step-up cluster timing data feed   → returns None, not scored

Usage:
    result = detect_sweep_risk("xyz:SILVER", ctx)
    # {"score": 0-3, "flags": [...], "reasoning": "...", "phase3_gaps": [...]}
"""
from __future__ import annotations

import logging
import time
from typing import Any, Dict, List, Optional

log = logging.getLogger("sweep_detector")

# ── Phase 3 gap annotations ───────────────────────────────────
PHASE3_GAPS = [
    "shanghai_physical_futures_spread — no data feed yet",
    "cftc_cot_positioning — no data feed yet",
    "step_up_cluster_timing — no timestamped cluster feed yet",
]


def _zone_within_atr(zones: list, current_price: float, atr: float,
                     position_side: str) -> Optional[dict]:
    """Find largest liquidation zone within 1.5 ATR on the adverse side.

    For a LONG: adverse side = below current price (downward sweep).
    For a SHORT: adverse side = above current price (upward squeeze).
    """
    if not zones or atr <= 0 or current_price <= 0:
        return None

    threshold = 1.5 * atr
    best = None
    best_notional = 0.0

    for zone in zones:
        instrument = str(zone.get("instrument", ""))
        centroid = float(zone.get("centroid", 0))
        notional = float(zone.get("notional_usd", 0))
        side = str(zone.get("side", "")).lower()  # "bid" or "ask"

        if not centroid or not notional:
            continue

        dist = abs(current_price - centroid)
        if dist > threshold:
            continue

        # For longs, we care about bid-side clusters below price (liquidation of longs)
        # For shorts, we care about ask-side clusters above price
        if position_side == "long" and centroid < current_price and side == "bid":
            if notional > best_notional:
                best_notional = notional
                best = zone
        elif position_side == "short" and centroid > current_price and side == "ask":
            if notional > best_notional:
                best_notional = notional
                best = zone

    return best


def _recent_cascade(cascades: list, market: str, lookback_hours: float = 18.0) -> Optional[dict]:
    """Return most recent cascade for this market within lookback window."""
    bare = market.replace("xyz:", "")
    now = time.time()
    cutoff = now - lookback_hours * 3600

    for cascade in sorted(cascades,
                          key=lambda c: c.get("ts", c.get("timestamp", 0)),
                          reverse=True):
        instrument = str(cascade.get("instrument", ""))
        ts_raw = cascade.get("ts", cascade.get("timestamp", 0))
        try:
            ts = float(ts_raw)
        except (TypeError, ValueError):
            continue
        if ts < cutoff:
            continue
        if bare in instrument.replace("xyz:", ""):
            return cascade

    return None


def _funding_adverse(funding_rate: Optional[float], position_side: str) -> bool:
    """Return True if funding is working against the position.

    Positive funding rate → longs pay shorts.
    If you're long and funding_rate > 0.002 (hourly), you're paying heavily.
    If you're short and funding_rate < -0.002 (hourly), you're paying.
    Threshold: 0.002/h ≈ 17.5% annualised — meaningful but not extreme.
    """
    if funding_rate is None:
        return False
    # HL funding field is 8-hour rate. 0.0001 = 0.01%/8h ≈ 10.95%/yr.
    # Threshold: flag if annualized cost > ~10%/yr adverse = 0.0001 per 8h
    threshold = 0.0001  # 0.01%/8h = 10.95%/yr — low-bar "building concern"
    if position_side == "long":
        return funding_rate > threshold
    else:  # short
        return funding_rate < -threshold


def _bot_pattern_sweep_signal(bot_patterns: list, market: str) -> bool:
    """Return True if bot classifier flagged a sweep pattern recently."""
    bare = market.replace("xyz:", "")
    sweep_keywords = {"sweep", "liquidation", "spoofing", "manipulation", "step_up", "cascade"}
    for bp in bot_patterns:
        instrument = str(bp.get("instrument", bp.get("coin", ""))).replace("xyz:", "")
        if bare.lower() not in instrument.lower():
            continue
        pattern_type = str(bp.get("pattern_type", bp.get("type", ""))).lower()
        tags = [str(t).lower() for t in bp.get("tags", [])]
        all_text = pattern_type + " " + " ".join(tags)
        if any(kw in all_text for kw in sweep_keywords):
            return True
    return False


def detect_sweep_risk(coin: str, ctx: dict) -> dict:
    """Main entry point. Returns scored sweep risk dict.

    Args:
        coin:   Coin identifier, with or without xyz: prefix.
        ctx:    Standard checklist context dict.

    Returns dict:
        score       int   0-3
        flags       list  human-readable flag descriptions
        reasoning   str   one-line summary
        phase3_gaps list  data sources not yet available
    """
    flags: List[str] = []
    severe = False  # A single severe combination bypasses score threshold

    positions = ctx.get("positions", [])
    market_price = ctx.get("market_price")
    atr = ctx.get("atr")
    funding_rate = ctx.get("funding_rate")
    zones = ctx.get("heatmap_zones", [])
    cascades = ctx.get("cascades", [])
    bot_patterns = ctx.get("bot_patterns", [])

    # Determine held position side
    bare = coin.replace("xyz:", "")
    pos = None
    for p in positions:
        pcoin = str(p.get("coin", "")).replace("xyz:", "")
        if pcoin == bare:
            pos = p
            break

    position_side = "long"
    if pos is not None:
        size = float(pos.get("size", 0))
        position_side = "long" if size >= 0 else "short"

    # ── Flag 1: Liquidation zone within 1.5 ATR ──────────────
    zone_data = None
    if market_price and atr and zones:
        zone_data = _zone_within_atr(zones, market_price, atr, position_side)
        if zone_data:
            notional_m = float(zone_data.get("notional_usd", 0)) / 1e6
            centroid = float(zone_data.get("centroid", 0))
            dist_pct = abs(market_price - centroid) / market_price * 100
            flags.append(
                f"Liquidation zone ${notional_m:.1f}M at ${centroid:,.2f} "
                f"({dist_pct:.1f}% from price, within 1.5 ATR)"
            )

    # ── Flag 2: Funding adverse ───────────────────────────────
    funding_flag = _funding_adverse(funding_rate, position_side)
    if funding_flag:
        # HL funding field = 8-hour rate; annualize by 3 * 365
        ann = (funding_rate or 0) * 3 * 365 * 100
        flags.append(
            f"Funding rate {(funding_rate or 0)*100:.4f}%/8h ({ann:.1f}%/yr) "
            f"adverse for {position_side}"
        )

    # ── Flag 3: Recent cascade ────────────────────────────────
    cascade = _recent_cascade(cascades, coin)
    if cascade:
        ts_raw = cascade.get("ts", cascade.get("timestamp", 0))
        hours_ago = (time.time() - float(ts_raw)) / 3600
        flags.append(f"Liquidation cascade {hours_ago:.1f}h ago on {bare}")

    # ── Flag 4: Bot pattern sweep signal ─────────────────────
    if _bot_pattern_sweep_signal(bot_patterns, coin):
        flags.append(f"Bot classifier flagged sweep/manipulation pattern on {bare}")

    # ── Severe: zone + funding + cascade = imminent ───────────
    if zone_data and funding_flag and cascade:
        severe = True

    # ── Score ─────────────────────────────────────────────────
    if severe or len(flags) >= 3:
        score = 3
    elif len(flags) == 2:
        score = 2
    elif len(flags) == 1:
        score = 1
    else:
        score = 0

    reasoning_parts = {
        0: "No sweep risk signals detected",
        1: "One sweep indicator building — monitor",
        2: "Two sweep indicators — elevated risk",
        3: "Imminent sweep risk — consider reducing before sleep",
    }

    return {
        "score": score,
        "flags": flags,
        "reasoning": reasoning_parts[score],
        "position_side": position_side,
        "phase3_gaps": PHASE3_GAPS,
    }
