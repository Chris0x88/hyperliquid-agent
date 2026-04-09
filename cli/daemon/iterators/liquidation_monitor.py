"""LiquidationMonitorIterator — tiered cushion alerts before ruin SL fires.

Walks ctx.positions every tick, computes liquidation cushion %, and emits
tiered alerts when positions get close to liquidation. Runs ahead of
exchange_protection (which places the actual ruin SL near liq) — its job
is to give the user early warning before things get bad enough that the
ruin SL even has to fire.

Tiers (cushion % = distance from current mark to liquidation price):
  >= 6%       — safe (no alert except recovery from a worse state)
  2% to 6%    — warning (alert on transition INTO this tier)
  < 2%        — critical (alert on transition + repeat every CRITICAL_REPEAT_TICKS)

Thresholds calibrated to ~20x leverage style (avg 19.8x observed): entry cushions
of 2-3% are normal operating range; 6%+ is comfortable; <2% is genuinely imminent.

Pure alert layer. Does NOT close positions, place orders, or modify state.
This is the "F6" early-warning piece referenced in docs/plans/AUDIT_FIX_PLAN.md.
"""
from __future__ import annotations

import logging
from decimal import Decimal
from typing import Dict

from cli.daemon.context import Alert, TickContext

log = logging.getLogger("daemon.liquidation_monitor")

ZERO = Decimal("0")

# Cushion thresholds (positive fraction = farther from liq = safer).
# Calibrated to ~20x leverage style: typical entry cushion is 2-3%, 6%+ is safe.
INFO_THRESHOLD = Decimal("0.06")   # >= 6% = safe
WARN_THRESHOLD = Decimal("0.02")   # 2-6% = warning, < 2% = critical

# Re-alert critical positions every N ticks so they stay visible
CRITICAL_REPEAT_TICKS = 10


def _classify(cushion: Decimal) -> str:
    if cushion >= INFO_THRESHOLD:
        return "safe"
    if cushion >= WARN_THRESHOLD:
        return "warning"
    return "critical"


class LiquidationMonitorIterator:
    """Per-position liquidation cushion monitor with tiered alerts."""

    name = "liquidation_monitor"

    def __init__(self) -> None:
        # Track last alert tier per instrument so we only alert on transitions
        self._last_tier: Dict[str, str] = {}
        # Track last critical-alert tick per instrument for repeat throttling
        self._last_critical_tick: Dict[str, int] = {}

    def on_start(self, ctx: TickContext) -> None:
        log.info(
            "LiquidationMonitor started  safe>=%d%%  warn>=%d%%  crit<%d%%  repeat=%d ticks",
            int(INFO_THRESHOLD * 100),
            int(WARN_THRESHOLD * 100),
            int(WARN_THRESHOLD * 100),
            CRITICAL_REPEAT_TICKS,
        )

    def on_stop(self) -> None:
        pass

    def tick(self, ctx: TickContext) -> None:
        seen_instruments = set()

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
                # liq is BELOW mark for longs
                cushion = (mark_dec - liq_dec) / mark_dec
            else:
                # liq is ABOVE mark for shorts
                cushion = (liq_dec - mark_dec) / mark_dec

            # Defensive: if already past liq, treat as critical
            if cushion < ZERO:
                cushion = ZERO

            tier = _classify(cushion)
            prev_tier = self._last_tier.get(inst, "safe")

            should_alert = False
            severity = "info"
            prefix = ""

            if tier == "critical":
                last_tick = self._last_critical_tick.get(inst, -CRITICAL_REPEAT_TICKS - 1)
                if prev_tier != "critical" or (ctx.tick_number - last_tick) >= CRITICAL_REPEAT_TICKS:
                    should_alert = True
                    severity = "critical"
                    prefix = "LIQUIDATION RISK CRITICAL "
                    self._last_critical_tick[inst] = ctx.tick_number

            elif tier == "warning":
                if prev_tier != "warning":
                    should_alert = True
                    severity = "warning"
                    prefix = "Approaching liquidation "

            elif tier == "safe":
                if prev_tier in ("warning", "critical"):
                    should_alert = True
                    severity = "info"
                    prefix = "RECOVERED "

            if should_alert:
                direction = "LONG" if is_long else "SHORT"
                cushion_pct = float(cushion) * 100
                lev_str = f"{float(pos.leverage):.1f}x" if pos.leverage else "?"
                # C4: append calendar regime tags so the operator knows what
                # market context this alert fired in
                from cli.daemon.calendar_tags import get_current_tags
                from cli.daemon.iterators._format import dir_dot, fmt_price, humanize_tags as _humanize_tags
                cal = get_current_tags()
                tag_suffix = f"\n  _{_humanize_tags(cal['tags'])}_" if cal["tags"] else ""
                # BUG-FIX 2026-04-08 (alert-format): replaced
                # ``cushion=3.6% mark=112.1900 liq=108.1349 lev=20.0x``
                # with a labelled markdown block the operator can read
                # at a glance.
                msg = (
                    f"{prefix.strip()}\n"
                    f"  {dir_dot(direction)} *{inst}* {direction} `{lev_str}`\n"
                    f"  Mark `{fmt_price(mark_dec)}` → Liq `{fmt_price(liq_dec)}`\n"
                    f"  Cushion `{cushion_pct:.1f}%`{tag_suffix}"
                )
                ctx.alerts.append(Alert(
                    severity=severity,
                    source=self.name,
                    message=msg,
                    data={
                        "instrument": inst,
                        "direction": direction.lower(),
                        "cushion_pct": cushion_pct,
                        "mark_price": float(mark_dec),
                        "liquidation_price": float(liq_dec),
                        "leverage": float(pos.leverage) if pos.leverage else None,
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
        gone = [inst for inst in self._last_tier if inst not in seen_instruments]
        for inst in gone:
            self._last_tier.pop(inst, None)
            self._last_critical_tick.pop(inst, None)
            log.debug("Cleaned cushion state for closed position: %s", inst)
