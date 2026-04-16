"""LiquidationMonitorIterator — leverage-aware cushion alerts before ruin SL fires.

Walks ctx.positions every tick, computes liquidation cushion %, and emits
tiered alerts when positions get close to liquidation. Runs ahead of
exchange_protection (which places the actual ruin SL near liq) — its job
is to give the user early warning before things get bad enough that the
ruin SL even has to fire.

Tiers use leverage-adjusted "turns" (cushion% × leverage) to normalize
risk across leverage levels. 2% cushion at 10x (0.20 turns) is totally
different from 2% at 37x (0.74 turns):

  >= 1.0 turns  — safe (no alert except recovery from a worse state)
  0.5 to 1.0    — warning (alert on transition INTO this tier, once only)
  < 0.5 turns   — critical (alert on transition + repeat every 30 min,
                   but ONLY if cushion actually worsened since last alert)

Concrete examples:
  10x lev, 6% cushion = 0.60 turns → warning (alert once)
  10x lev, 3% cushion = 0.30 turns → critical
  20x lev, 3% cushion = 0.60 turns → warning
  37x lev, 3% cushion = 1.11 turns → safe
  37x lev, 1% cushion = 0.37 turns → critical

Anti-spam rules:
  1. Warning fires ONCE per transition (no repeats)
  2. Critical repeats only if cushion got worse (>0.1% delta) since last alert
  3. Critical repeat interval is time-based (30 min), not tick-based
  4. Oscillation dampening: transitioning warning→safe requires 20% hysteresis
     above the safe threshold to prevent boundary jitter alerts

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

# Leverage-adjusted "turns" thresholds.
# turns = cushion_fraction × leverage
# Higher leverage positions need less % cushion to be "normal".
SAFE_TURNS = Decimal("1.0")     # >= 1.0 turns = comfortable
WARN_TURNS = Decimal("0.5")     # 0.5-1.0 turns = warning, < 0.5 = critical

# Hysteresis: to transition from warning→safe, need 20% above safe threshold.
# Prevents oscillation spam when price bounces around the boundary.
SAFE_HYSTERESIS = Decimal("1.2")  # need 1.2 × SAFE_TURNS to recover

# Critical repeat: time-based (seconds), not tick-based.
# Only re-alerts if cushion actually worsened.
CRITICAL_REPEAT_SECS = 1800  # 30 minutes
CRITICAL_WORSENED_DELTA = Decimal("0.001")  # must worsen by >0.1% to re-fire


def _classify(turns: Decimal, prev_tier: str) -> str:
    """Classify risk tier with hysteresis on the safe boundary."""
    if prev_tier == "warning":
        # Need extra clearance to transition back to safe (anti-oscillation)
        if turns >= SAFE_TURNS * SAFE_HYSTERESIS:
            return "safe"
        if turns >= WARN_TURNS:
            return "warning"  # stay in warning
        return "critical"
    # Normal classification
    if turns >= SAFE_TURNS:
        return "safe"
    if turns >= WARN_TURNS:
        return "warning"
    return "critical"


class LiquidationMonitorIterator:
    """Per-position liquidation cushion monitor with leverage-adjusted alerts."""

    name = "liquidation_monitor"

    def __init__(self) -> None:
        # Track last alert tier per instrument so we only alert on transitions
        self._last_tier: Dict[str, str] = {}
        # Track last critical-alert time (epoch seconds) per instrument
        self._last_critical_time: Dict[str, float] = {}
        # Track last alerted cushion per instrument (for worsening check)
        self._last_alert_cushion: Dict[str, Decimal] = {}

    def on_start(self, ctx: TickContext) -> None:
        log.info(
            "LiquidationMonitor started  safe>=%.1f turns  warn>=%.1f turns  "
            "crit<%.1f turns  repeat=%ds (if worsened)",
            float(SAFE_TURNS), float(WARN_TURNS), float(WARN_TURNS),
            CRITICAL_REPEAT_SECS,
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

            # Need both liquidation price and current mark price
            liq_px = pos.liquidation_price
            if liq_px is None or liq_px <= ZERO:
                continue  # exchange didn't report a liq price — skip silently

            mark_px = ctx.prices.get(inst)
            if mark_px is None or Decimal(str(mark_px)) <= ZERO:
                continue  # no mark — skip

            mark_dec = Decimal(str(mark_px))
            liq_dec = Decimal(str(liq_px))

            # Cushion as positive fraction of mark
            is_long = pos.net_qty > ZERO
            if is_long:
                cushion = (mark_dec - liq_dec) / mark_dec
            else:
                cushion = (liq_dec - mark_dec) / mark_dec

            # Defensive: if already past liq, treat as critical
            if cushion < ZERO:
                cushion = ZERO

            # Leverage-adjusted turns: normalize across leverage levels
            leverage = pos.leverage if pos.leverage else Decimal("1")
            turns = cushion * Decimal(str(leverage))

            prev_tier = self._last_tier.get(inst, "safe")
            tier = _classify(turns, prev_tier)

            should_alert = False
            severity = "info"
            prefix = ""
            now = time.monotonic()

            if tier == "critical":
                last_time = self._last_critical_time.get(inst, 0.0)
                last_cushion = self._last_alert_cushion.get(inst, ONE)
                time_elapsed = now - last_time >= CRITICAL_REPEAT_SECS
                worsened = (last_cushion - cushion) > CRITICAL_WORSENED_DELTA

                if prev_tier != "critical":
                    # First transition into critical — always alert
                    should_alert = True
                elif time_elapsed and worsened:
                    # Repeat only if enough time passed AND cushion got worse
                    should_alert = True

                if should_alert:
                    severity = "critical"
                    prefix = "LIQUIDATION RISK CRITICAL "
                    self._last_critical_time[inst] = now
                    self._last_alert_cushion[inst] = cushion

            elif tier == "warning":
                if prev_tier != "warning":
                    # Warning fires exactly once per transition
                    should_alert = True
                    severity = "warning"
                    prefix = "Approaching liquidation "
                    self._last_alert_cushion[inst] = cushion

            elif tier == "safe":
                if prev_tier in ("warning", "critical"):
                    should_alert = True
                    severity = "info"
                    prefix = "RECOVERED "
                    # Clear critical tracking on recovery
                    self._last_critical_time.pop(inst, None)
                    self._last_alert_cushion.pop(inst, None)

            if should_alert:
                direction = "LONG" if is_long else "SHORT"
                cushion_pct = float(cushion) * 100
                turns_f = float(turns)
                lev_str = f"{float(leverage):.0f}x"
                # C4: append calendar regime tags so the operator knows what
                # market context this alert fired in
                from daemon.calendar_tags import get_current_tags
                from daemon.iterators._format import dir_dot, fmt_price, humanize_tags as _humanize_tags
                cal = get_current_tags()
                tag_suffix = f"\n  _{_humanize_tags(cal['tags'])}_" if cal["tags"] else ""
                msg = (
                    f"{prefix.strip()}\n"
                    f"  {dir_dot(direction)} *{inst}* {direction} `{lev_str}`\n"
                    f"  Mark `{fmt_price(mark_dec)}` → Liq `{fmt_price(liq_dec)}`\n"
                    f"  Cushion `{cushion_pct:.1f}%` ({turns_f:.2f} turns){tag_suffix}"
                )
                ctx.alerts.append(Alert(
                    severity=severity,
                    source=self.name,
                    message=msg,
                    data={
                        "instrument": inst,
                        "direction": direction.lower(),
                        "cushion_pct": cushion_pct,
                        "turns": turns_f,
                        "mark_price": float(mark_dec),
                        "liquidation_price": float(liq_dec),
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
            self._last_alert_cushion.pop(inst, None)
            log.debug("Cleaned cushion state for closed position: %s", inst)
