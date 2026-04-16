"""LiquidationMonitorIterator — margin-burn alerts before ruin SL fires.

Walks ctx.positions every tick, computes how much of the initial margin
has been consumed, and emits tiered alerts when positions approach liquidation.

The key metric is **margin_remaining** = current_cushion / entry_cushion.
This tells you what fraction of your starting safety margin is left.
At entry price, margin_remaining = 100% (safe by definition, any leverage).
At liquidation, margin_remaining = 0%.

Tiers (margin_remaining = fraction of initial cushion still intact):
  >= 50%     — safe (no alert except recovery from a worse state)
  25% to 50% — warning (alert on transition INTO this tier, once only)
  < 25%      — critical (alert + repeat every 30 min IF worsened)

This works at ALL leverage levels because it's relative to your entry:
  25x, at entry price  → margin_remaining=100% → safe ✓
  25x, lost half margin → margin_remaining=50%  → warning
  10x, at entry price  → margin_remaining=100% → safe ✓
  10x, lost half margin → margin_remaining=50%  → warning
  Any leverage, price at entry → ALWAYS safe. No false alarms.

Anti-spam rules:
  1. Warning fires ONCE per transition (no repeats)
  2. Critical repeats only if margin got worse (>2pp delta) since last alert
  3. Critical repeat interval is time-based (30 min), not tick-based
  4. Oscillation dampening: warning→safe requires 10pp hysteresis above safe

Pure alert layer. Does NOT close positions, place orders, or modify state.
This is the "F6" early-warning piece referenced in docs/plans/AUDIT_FIX_PLAN.md.
"""
from __future__ import annotations

import logging
import time
from decimal import Decimal
from typing import Dict, Optional

from daemon.context import Alert, TickContext

log = logging.getLogger("daemon.liquidation_monitor")

ZERO = Decimal("0")
ONE = Decimal("1")
HUNDRED = Decimal("100")

# Margin-remaining thresholds (fraction of initial cushion still intact).
# At entry price, margin_remaining = 1.0 (100%) — always safe.
# At liquidation, margin_remaining = 0.0 (0%).
SAFE_THRESHOLD = Decimal("0.50")     # >= 50% of initial margin left = safe
WARN_THRESHOLD = Decimal("0.25")     # 25%-50% = warning, < 25% = critical

# Hysteresis: to transition from warning→safe, need this much above safe.
# Prevents oscillation spam when price bounces around the boundary.
SAFE_HYSTERESIS = Decimal("0.60")  # need 60% to recover from warning

# Critical repeat: time-based (seconds), not tick-based.
# Only re-alerts if margin actually worsened.
CRITICAL_REPEAT_SECS = 1800  # 30 minutes
CRITICAL_WORSENED_DELTA = Decimal("0.02")  # must worsen by >2pp to re-fire


def _classify(margin_remaining: Decimal, prev_tier: str) -> str:
    """Classify risk tier with hysteresis on the safe boundary."""
    if prev_tier == "warning":
        # Need extra clearance to transition back to safe (anti-oscillation)
        if margin_remaining >= SAFE_HYSTERESIS:
            return "safe"
        if margin_remaining >= WARN_THRESHOLD:
            return "warning"  # stay in warning
        return "critical"
    # Normal classification
    if margin_remaining >= SAFE_THRESHOLD:
        return "safe"
    if margin_remaining >= WARN_THRESHOLD:
        return "warning"
    return "critical"


class LiquidationMonitorIterator:
    """Per-position margin-burn monitor. Alerts based on how much initial margin is consumed."""

    name = "liquidation_monitor"

    def __init__(self) -> None:
        # Track last alert tier per instrument so we only alert on transitions
        self._last_tier: Dict[str, str] = {}
        # Track last critical-alert time (epoch seconds) per instrument
        self._last_critical_time: Dict[str, float] = {}
        # Track last alerted margin_remaining per instrument (for worsening check)
        self._last_alert_margin: Dict[str, Decimal] = {}

    def on_start(self, ctx: TickContext) -> None:
        log.info(
            "LiquidationMonitor started  safe>=%.0f%%  warn>=%.0f%%  crit<%.0f%%  repeat=%ds (if worsened)",
            float(SAFE_THRESHOLD * 100), float(WARN_THRESHOLD * 100),
            float(WARN_THRESHOLD * 100), CRITICAL_REPEAT_SECS,
        )

    def on_stop(self) -> None:
        pass

    def tick(self, ctx: TickContext) -> None:
        seen_instruments: set[str] = set()

        for pos in ctx.positions:
            if pos.net_qty == ZERO:
                continue

            inst = pos.instrument
            seen_instruments.add(inst)

            # Need liquidation price, mark price, AND entry price
            liq_px = pos.liquidation_price
            if liq_px is None or liq_px <= ZERO:
                continue

            mark_px = ctx.prices.get(inst)
            if mark_px is None or Decimal(str(mark_px)) <= ZERO:
                continue

            entry_px = pos.avg_entry_price
            if entry_px is None or entry_px <= ZERO:
                continue

            mark_dec = Decimal(str(mark_px))
            liq_dec = Decimal(str(liq_px))
            entry_dec = Decimal(str(entry_px))
            is_long = pos.net_qty > ZERO

            # Current cushion = distance from mark to liq (as fraction of mark)
            if is_long:
                current_cushion = mark_dec - liq_dec
                entry_cushion = entry_dec - liq_dec
            else:
                current_cushion = liq_dec - mark_dec
                entry_cushion = liq_dec - entry_dec

            # Defensive: clamp to zero
            if current_cushion < ZERO:
                current_cushion = ZERO
            if entry_cushion <= ZERO:
                # Edge case: liq is at or beyond entry (shouldn't happen, but defensive)
                entry_cushion = ONE  # avoid division by zero, treat as max risk

            # margin_remaining = what fraction of initial cushion is left
            # At entry price: margin_remaining = 1.0 (100%)
            # At liquidation: margin_remaining = 0.0 (0%)
            # Above entry: margin_remaining > 1.0 (in profit, extra safe)
            margin_remaining = current_cushion / entry_cushion

            cushion_pct = (float(current_cushion) / float(mark_dec)) * 100 if mark_dec > ZERO else 0.0
            margin_pct = float(margin_remaining) * 100

            prev_tier = self._last_tier.get(inst, "safe")
            tier = _classify(margin_remaining, prev_tier)

            should_alert = False
            severity = "info"
            prefix = ""
            now = time.monotonic()

            if tier == "critical":
                last_time = self._last_critical_time.get(inst, 0.0)
                last_margin = self._last_alert_margin.get(inst, ONE)
                time_elapsed = now - last_time >= CRITICAL_REPEAT_SECS
                worsened = (last_margin - margin_remaining) > CRITICAL_WORSENED_DELTA

                if prev_tier != "critical":
                    should_alert = True
                elif time_elapsed and worsened:
                    should_alert = True

                if should_alert:
                    severity = "critical"
                    prefix = "LIQUIDATION RISK "
                    self._last_critical_time[inst] = now
                    self._last_alert_margin[inst] = margin_remaining

            elif tier == "warning":
                if prev_tier != "warning":
                    should_alert = True
                    severity = "warning"
                    prefix = "Margin warning "
                    self._last_alert_margin[inst] = margin_remaining

            elif tier == "safe":
                if prev_tier in ("warning", "critical"):
                    should_alert = True
                    severity = "info"
                    prefix = "RECOVERED "
                    self._last_critical_time.pop(inst, None)
                    self._last_alert_margin.pop(inst, None)

            if should_alert:
                direction = "LONG" if is_long else "SHORT"
                leverage = pos.leverage if pos.leverage else Decimal("1")
                lev_str = f"{float(leverage):.0f}x"
                from daemon.calendar_tags import get_current_tags
                from daemon.iterators._format import dir_dot, fmt_price, humanize_tags as _humanize_tags
                cal = get_current_tags()
                tag_suffix = f"\n  _{_humanize_tags(cal['tags'])}_" if cal["tags"] else ""
                msg = (
                    f"{prefix.strip()}\n"
                    f"  {dir_dot(direction)} *{inst}* {direction} `{lev_str}`\n"
                    f"  Mark `{fmt_price(mark_dec)}` → Liq `{fmt_price(liq_dec)}`\n"
                    f"  Margin left `{margin_pct:.0f}%` · cushion `{cushion_pct:.1f}%`{tag_suffix}"
                )
                ctx.alerts.append(Alert(
                    severity=severity,
                    source=self.name,
                    message=msg,
                    data={
                        "instrument": inst,
                        "direction": direction.lower(),
                        "cushion_pct": cushion_pct,
                        "margin_remaining_pct": margin_pct,
                        "mark_price": float(mark_dec),
                        "liquidation_price": float(liq_dec),
                        "entry_price": float(entry_dec),
                        "leverage": float(leverage),
                        "tier": tier,
                        "previous_tier": prev_tier,
                        "calendar_tags": cal["tags"],
                        "weekend": cal["weekend"],
                        "thin_session": cal["thin_session"],
                        "high_impact_event_24h": cal["high_impact_event_24h"],
                    },
                ))
                log.info("[%s] %s", severity, msg)

            self._last_tier[inst] = tier

        # Clean up state for closed positions
        gone = [inst for inst in list(self._last_tier) if inst not in seen_instruments]
        for inst in gone:
            self._last_tier.pop(inst, None)
            self._last_critical_time.pop(inst, None)
            self._last_alert_margin.pop(inst, None)
            log.debug("Cleaned cushion state for closed position: %s", inst)
