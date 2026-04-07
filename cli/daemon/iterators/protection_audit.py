"""ProtectionAuditIterator — read-only check that every open position has an exchange stop.

This is C1' from the 2026-04-07 connections audit. It replaces the original
proposal of "add exchange_protection to WATCH" which would have created a
coordination bug with the heartbeat process (different stop formula, no
authority check, both fighting to manage the same SL).

Instead this iterator is a defensive monitor: it never writes to the
exchange. Every cycle it fetches existing trigger orders for the main
wallet (native + xyz dex), maps them to positions in ctx.positions, and
emits tiered alerts when:

  - A position has NO matching stop on the exchange (CRITICAL)
  - A stop exists but is on the wrong side of entry (CRITICAL)
  - A stop exists but is implausibly far from current price (WARNING)
  - A stop exists and looks reasonable (no alert, info log only)

Why this matters: the heartbeat process places ATR-based stops every 2 min
via launchd. If it fails (network, auth, exchange downtime, hung process)
the daemon today has no visibility into it — positions can sit unguarded.
This iterator gives the daemon a second opinion on protection state and
loudly surfaces gaps.

Coordination model:
  - heartbeat = SL placer (writes to exchange)
  - protection_audit = SL verifier (reads from exchange, alerts on gaps)
  - liquidation_monitor = cushion alerter (reads ctx.positions, alerts on tier transitions)

The three together form the WATCH-tier defense story. None of them place
new entries. None of them touch positions other than to verify protection.
"""
from __future__ import annotations

import logging
import time
from decimal import Decimal
from typing import Dict, List, Optional

from cli.daemon.context import Alert, TickContext

log = logging.getLogger("daemon.protection_audit")

ZERO = Decimal("0")

# Throttle — match heartbeat cadence so we audit at the same frequency it
# would have placed stops.
CHECK_INTERVAL_S = 120

# A "reasonable" stop is between MIN and MAX fraction away from current price.
# Below MIN: stop is hugging price too tightly, will get hunted. Probably wrong.
# Above MAX: stop is so far away it's effectively no protection.
MIN_STOP_DISTANCE_PCT = Decimal("0.005")   # 0.5%
MAX_STOP_DISTANCE_PCT = Decimal("0.50")    # 50%


def _coin_matches(stop_coin: str, pos_coin: str) -> bool:
    """Match a trigger order's coin against a position's instrument.

    Handles the xyz: prefix recurring bug — both forms are valid.
    """
    if stop_coin == pos_coin:
        return True
    return stop_coin.replace("xyz:", "") == pos_coin.replace("xyz:", "")


class ProtectionAuditIterator:
    """Read-only verifier that every open position has a sane exchange stop."""

    name = "protection_audit"

    def __init__(self) -> None:
        self._last_check: float = 0.0
        # Track last alert state per coin so we don't spam every tick
        # State values: "ok" | "no_stop" | "wrong_side" | "too_close" | "too_far"
        self._last_state: Dict[str, str] = {}

    def on_start(self, ctx: TickContext) -> None:
        log.info(
            "ProtectionAudit started  interval=%ds  min_dist=%.1f%%  max_dist=%.0f%%",
            CHECK_INTERVAL_S,
            float(MIN_STOP_DISTANCE_PCT) * 100,
            float(MAX_STOP_DISTANCE_PCT) * 100,
        )

    def on_stop(self) -> None:
        pass

    def tick(self, ctx: TickContext) -> None:
        now = time.monotonic()
        if now - self._last_check < CHECK_INTERVAL_S:
            return
        self._last_check = now

        # Nothing to audit if there are no positions
        live_positions = [p for p in ctx.positions if p.net_qty != ZERO]
        if not live_positions:
            # Drop any tracked state for closed positions
            self._last_state.clear()
            return

        triggers = self._fetch_all_triggers()
        if triggers is None:
            log.debug("ProtectionAudit: trigger fetch unavailable, skipping cycle")
            return

        # Build coin → list of stop trigger orders
        # Filter to STOP triggers only, not take-profit
        stops_by_coin: Dict[str, List[dict]] = {}
        for t in triggers:
            if not self._is_stop_trigger(t):
                continue
            tcoin = t.get("coin", "")
            if not tcoin:
                continue
            stops_by_coin.setdefault(tcoin, []).append(t)

        seen_coins = set()
        for pos in live_positions:
            inst = pos.instrument
            seen_coins.add(inst)
            self._audit_position(pos, stops_by_coin, ctx)

        # Clean up state for closed positions
        gone = [c for c in self._last_state if c not in seen_coins]
        for c in gone:
            self._last_state.pop(c, None)

    # ── Internals ────────────────────────────────────────────────────

    def _fetch_all_triggers(self) -> Optional[List[dict]]:
        """Fetch trigger orders for main wallet (native + xyz dex).

        Returns None on resolver/import failure (treated as 'unavailable',
        cycle is skipped without alerting). Returns [] if everything worked
        but the wallet has no triggers.
        """
        try:
            from common.account_resolver import resolve_main_wallet
            from common.heartbeat import _fetch_open_trigger_orders
        except Exception as e:
            log.debug("ProtectionAudit imports unavailable: %s", e)
            return None

        try:
            main_addr = resolve_main_wallet(required=False)
        except Exception as e:
            log.debug("ProtectionAudit cannot resolve main wallet: %s", e)
            return None

        if not main_addr:
            return None

        triggers: List[dict] = []
        try:
            triggers.extend(_fetch_open_trigger_orders(main_addr) or [])
        except Exception as e:
            log.debug("ProtectionAudit native fetch failed: %s", e)
        try:
            triggers.extend(_fetch_open_trigger_orders(main_addr, dex="xyz") or [])
        except Exception as e:
            log.debug("ProtectionAudit xyz fetch failed: %s", e)

        return triggers

    @staticmethod
    def _is_stop_trigger(order: dict) -> bool:
        """Return True if this trigger order looks like a stop-loss (not a TP).

        BUG-FIX 2026-04-08: HL's ``frontendOpenOrders`` endpoint does NOT
        populate the ``tpsl`` field on the orders it returns — it only sets
        ``orderType`` to ``"Stop Market"`` for stop-losses and
        ``"Take Profit Market"`` for take-profits. The previous fallback
        defaulted to ``bool(order.get("isTrigger") or order.get("triggerCondition"))``
        which returned True for *every* trigger order — so take-profits
        slipped through the filter and ended up in ``stops_by_coin``,
        which made the wrong-side check at ``_audit_position`` line ~250
        emit a spurious ``WRONG-SIDE STOP`` CRITICAL alert for any TP that
        was (correctly) above entry on a long. The user just hit this on
        an xyz:SP500 LONG with a TP at 6773.9 (above entry 6564.5).

        Order of checks:
        1. ``tpsl == "sl"`` → SL (kept for forward-compat with API responses
           that DO populate this field, e.g. fills/place_trigger_order echoes)
        2. ``tpsl == "tp"`` → TP
        3. ``orderType`` contains ``"Take Profit"`` → TP (HL frontendOpenOrders)
        4. ``orderType`` contains ``"Stop"`` → SL (HL frontendOpenOrders)
        5. Default → NOT a stop (conservative; better to under-classify
           than to default-True and falsely alert)
        """
        tpsl = order.get("tpsl", "")
        if tpsl == "sl":
            return True
        if tpsl == "tp":
            return False
        order_type = str(order.get("orderType", ""))
        if "Take Profit" in order_type:
            return False
        if "Stop" in order_type:
            return True
        return False

    def _audit_position(
        self,
        pos,
        stops_by_coin: Dict[str, List[dict]],
        ctx: TickContext,
    ) -> None:
        inst = pos.instrument
        is_long = pos.net_qty > ZERO
        entry = pos.avg_entry_price
        mark_raw = ctx.prices.get(inst)
        mark = Decimal(str(mark_raw)) if mark_raw is not None else ZERO

        # Find any stop with a matching coin (handles xyz: prefix)
        matching_stops: List[dict] = []
        for stop_coin, stops in stops_by_coin.items():
            if _coin_matches(stop_coin, inst):
                matching_stops.extend(stops)

        prev_state = self._last_state.get(inst, "ok")

        if not matching_stops:
            new_state = "no_stop"
            if prev_state != new_state:
                self._emit_alert(
                    ctx,
                    severity="critical",
                    inst=inst,
                    direction="LONG" if is_long else "SHORT",
                    msg=(
                        f"UNGUARDED: {inst} "
                        f"{'LONG' if is_long else 'SHORT'} has NO exchange stop. "
                        f"Heartbeat may have failed. "
                        f"Entry={float(entry):.4f} mark={float(mark):.4f}"
                    ),
                    state=new_state,
                )
            self._last_state[inst] = new_state
            return

        # Pick the closest stop to current price (the "active" one)
        if mark > ZERO:
            chosen = min(
                matching_stops,
                key=lambda s: abs(Decimal(str(s.get("triggerPx") or s.get("limitPx") or 0)) - mark),
            )
        else:
            chosen = matching_stops[0]

        try:
            stop_px = Decimal(str(chosen.get("triggerPx") or chosen.get("limitPx") or 0))
        except Exception:
            stop_px = ZERO

        if stop_px <= ZERO:
            new_state = "no_stop"
            if prev_state != new_state:
                self._emit_alert(
                    ctx,
                    severity="critical",
                    inst=inst,
                    direction="LONG" if is_long else "SHORT",
                    msg=f"INVALID STOP: {inst} trigger order has trigger_price=0",
                    state=new_state,
                )
            self._last_state[inst] = new_state
            return

        # Side check: long stops must be BELOW entry, short stops ABOVE
        wrong_side = False
        if is_long and stop_px >= entry:
            wrong_side = True
        if not is_long and stop_px <= entry:
            wrong_side = True

        if wrong_side:
            new_state = "wrong_side"
            if prev_state != new_state:
                self._emit_alert(
                    ctx,
                    severity="critical",
                    inst=inst,
                    direction="LONG" if is_long else "SHORT",
                    msg=(
                        f"WRONG-SIDE STOP: {inst} {'LONG' if is_long else 'SHORT'} "
                        f"stop={float(stop_px):.4f} on wrong side of entry={float(entry):.4f}"
                    ),
                    state=new_state,
                )
            self._last_state[inst] = new_state
            return

        # Distance check (only meaningful if mark price is known)
        new_state = "ok"
        if mark > ZERO:
            distance = abs(mark - stop_px) / mark
            if distance < MIN_STOP_DISTANCE_PCT:
                new_state = "too_close"
                if prev_state != new_state:
                    self._emit_alert(
                        ctx,
                        severity="warning",
                        inst=inst,
                        direction="LONG" if is_long else "SHORT",
                        msg=(
                            f"STOP TOO CLOSE: {inst} stop={float(stop_px):.4f} "
                            f"is {float(distance) * 100:.2f}% from mark={float(mark):.4f} "
                            f"(< {float(MIN_STOP_DISTANCE_PCT) * 100:.1f}% — likely to be hunted)"
                        ),
                        state=new_state,
                    )
            elif distance > MAX_STOP_DISTANCE_PCT:
                new_state = "too_far"
                if prev_state != new_state:
                    self._emit_alert(
                        ctx,
                        severity="warning",
                        inst=inst,
                        direction="LONG" if is_long else "SHORT",
                        msg=(
                            f"STOP TOO FAR: {inst} stop={float(stop_px):.4f} "
                            f"is {float(distance) * 100:.0f}% from mark={float(mark):.4f} "
                            f"(> {float(MAX_STOP_DISTANCE_PCT) * 100:.0f}% — effectively no protection)"
                        ),
                        state=new_state,
                    )

        # Recovery alert when state returns to ok from any bad state
        if new_state == "ok" and prev_state != "ok":
            self._emit_alert(
                ctx,
                severity="info",
                inst=inst,
                direction="LONG" if is_long else "SHORT",
                msg=(
                    f"PROTECTION RESTORED: {inst} stop={float(stop_px):.4f} "
                    f"now reasonable vs mark={float(mark):.4f}"
                ),
                state=new_state,
            )

        self._last_state[inst] = new_state

    def _emit_alert(
        self,
        ctx: TickContext,
        severity: str,
        inst: str,
        direction: str,
        msg: str,
        state: str,
    ) -> None:
        ctx.alerts.append(Alert(
            severity=severity,
            source=self.name,
            message=msg,
            data={
                "instrument": inst,
                "direction": direction.lower(),
                "state": state,
            },
        ))
        log.info("[%s] %s", severity, msg)
