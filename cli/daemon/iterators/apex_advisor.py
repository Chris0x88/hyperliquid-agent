"""ApexAdvisorIterator — dry-run APEX evaluator that proposes but never executes.

This is C3 from the 2026-04-07 connections audit. APEX (modules/apex_engine.py)
is a complete decision engine but has been dead code in the daemon — its only
caller is skills/apex/scripts/standalone_runner.py, which is not what runs in
production.

This iterator brings APEX online as an ADVISOR. Each cycle:

  1. Build an ApexState that mirrors the daemon's actual open positions
     (one slot per real position) so the engine sees current reality
  2. Read pulse_signals + radar_opportunities populated by the pulse and
     radar iterators on the same tick
  3. Call ApexEngine.evaluate() with current state + signals + prices
  4. For each ApexAction the engine proposes, log it and emit a Telegram
     alert tagged 'apex_advisor'
  5. NEVER queue an OrderIntent. NEVER touch the exchange.

Why "advisor" not "executor": the user explicitly wants to run in WATCH tier
(observe-only) until the system has earned enough trust to be promoted past
WATCH. The advisor lets APEX prove its judgement against real signals before
any real money flows through it. After a week of clean proposals the user
can decide whether to graduate this iterator into a true executor (which is
what execution_engine in REBALANCE/OPPORTUNISTIC tiers does).

Throttle: 60s. Even at the slowest, the throttle is finer than pulse (120s)
and radar (300s) so the advisor never misses a fresh signal.

Heartbeat log: emits one INFO log line per cycle even when there are no
proposals, so the operator can see the advisor is alive and silent on
purpose. Quiet markets should produce a stream of "advised: no proposals
(N pulse, M radar, K positions)" lines, NOT a confusing absence of output.
"""
from __future__ import annotations

import logging
import time
from typing import Dict, List, Optional

from cli.daemon.context import Alert, TickContext

log = logging.getLogger("daemon.apex_advisor")

# Throttle: run at most once per 60s. APEX proposes on signal cadence, not
# market tick cadence — there's no benefit to running it faster than the
# slowest input updates.
ADVISE_INTERVAL_S = 60

# Default APEX config knobs for advisor mode. We don't want it proposing
# enormous slot counts; 3 is the same default as standalone_runner.
ADVISOR_MAX_SLOTS = 3


class ApexAdvisorIterator:
    """Dry-run APEX advisor — proposes actions, logs them, emits alerts."""

    name = "apex_advisor"

    def __init__(self) -> None:
        self._engine = None
        self._config = None
        self._last_advise: float = 0.0
        # Track last proposed action key per (instrument, action) so we don't
        # spam the same proposal every cycle while signals persist.
        self._last_proposal: Dict[str, str] = {}

    def on_start(self, ctx: TickContext) -> None:
        try:
            from modules.apex_config import ApexConfig
            from modules.apex_engine import ApexEngine
        except Exception as e:
            log.warning("ApexAdvisor: failed to import APEX modules: %s", e)
            return
        try:
            self._config = ApexConfig(max_slots=ADVISOR_MAX_SLOTS)
        except Exception as e:
            # Some ApexConfig fields require positional/runtime values; fall
            # back to bare construction.
            log.debug("ApexConfig with kwargs failed (%s); using bare init", e)
            try:
                self._config = ApexConfig()
            except Exception as e2:
                log.warning("ApexAdvisor: ApexConfig init failed: %s", e2)
                return
        try:
            self._engine = ApexEngine(self._config)
        except Exception as e:
            log.warning("ApexAdvisor: ApexEngine init failed: %s", e)
            return
        log.info(
            "ApexAdvisor started  max_slots=%d  interval=%ds  mode=DRY_RUN (proposes only, never executes)",
            ADVISOR_MAX_SLOTS,
            ADVISE_INTERVAL_S,
        )

    def on_stop(self) -> None:
        pass

    def tick(self, ctx: TickContext) -> None:
        if self._engine is None or self._config is None:
            return  # init failed; silent skip

        now = time.monotonic()
        if now - self._last_advise < ADVISE_INTERVAL_S:
            return
        self._last_advise = now

        try:
            self._advise(ctx)
        except Exception as e:
            log.warning("ApexAdvisor: cycle failed: %s", e)

    # ── Internals ───────────────────────────────────────────────────

    def _advise(self, ctx: TickContext) -> None:
        from modules.apex_state import ApexState, ApexSlot

        pulse_signals: List[Dict] = list(ctx.pulse_signals or [])
        radar_opps: List[Dict] = list(ctx.radar_opportunities or [])
        positions = [p for p in ctx.positions if p.net_qty != 0]

        # Build a state mirroring current reality. One ApexSlot per active
        # position; remaining slots stay empty for the engine to fill.
        state = ApexState.new(self._config.max_slots)
        now_ms = int(time.time() * 1000)

        # Fill slots with real positions, in order, up to max_slots.
        # APEX's candidate generator builds instruments as "asset + '-PERP'"
        # (e.g. "BTC" → "BTC-PERP"), so we must normalize the position's
        # instrument field to that form when mirroring or the engine will
        # propose duplicate entries on assets we already hold.
        for i, pos in enumerate(positions[: self._config.max_slots]):
            slot = state.slots[i]
            slot.status = "active"
            slot.instrument = self._normalize_instrument(pos.instrument)
            slot.direction = "long" if pos.net_qty > 0 else "short"
            slot.entry_price = float(pos.avg_entry_price)
            slot.entry_size = float(abs(pos.net_qty))
            slot.entry_ts = now_ms
            slot.entry_source = "mirror"

        # Build slot_prices map: slot_id → current mark price
        slot_prices: Dict[int, float] = {}
        for slot in state.active_slots():
            mark = ctx.prices.get(slot.instrument)
            if mark is not None:
                slot_prices[slot.slot_id] = float(mark)

        # No guard results in advisor mode (we don't run guard_bridge here)
        slot_guard_results: Dict[int, Dict] = {}

        try:
            actions = self._engine.evaluate(
                state=state,
                pulse_signals=pulse_signals,
                radar_opps=radar_opps,
                slot_prices=slot_prices,
                slot_guard_results=slot_guard_results,
                now_ms=now_ms,
            )
        except Exception as e:
            log.warning("ApexAdvisor: engine.evaluate failed: %s", e)
            return

        # Heartbeat log so the operator can SEE the advisor is alive even
        # when it has nothing to say. Quiet markets should produce a steady
        # stream of these lines.
        actionable = [a for a in actions if a.action != "noop"]
        log.info(
            "ApexAdvisor cycle: pulse=%d radar=%d positions=%d → %d proposed",
            len(pulse_signals), len(radar_opps), len(positions), len(actionable),
        )

        if not actionable:
            # No proposals — drop any stale proposal-state entries for
            # closed positions so we re-alert if the same proposal returns.
            current_keys = {p.instrument for p in positions}
            self._last_proposal = {
                k: v for k, v in self._last_proposal.items()
                if k in current_keys
            }
            return

        for action in actionable:
            self._handle_action(ctx, action)

    @staticmethod
    def _normalize_instrument(inst: str) -> str:
        """Normalize a position instrument to APEX's '<asset>-PERP' form.

        APEX's candidate generator (apex_engine._evaluate_entries) builds
        candidate instruments as ``sig['asset'] + '-PERP'``. To make the
        active_instruments check work correctly we must mirror real
        positions to the same convention.

        Rules:
          - Already ends with '-PERP'  → unchanged
          - Has an 'xyz:' prefix       → unchanged (xyz dex perps are
            named differently and APEX won't generate candidates for them
            from the standard pulse/radar feeds anyway)
          - Otherwise                  → append '-PERP'
        """
        if not inst:
            return inst
        if inst.endswith("-PERP"):
            return inst
        if ":" in inst:  # e.g. xyz:BRENTOIL
            return inst
        return inst + "-PERP"

    def _handle_action(self, ctx: TickContext, action) -> None:
        # Build a stable key so we don't re-alert the same proposal every
        # 60s while the underlying signal persists.
        key = action.instrument or f"slot{action.slot_id}"
        proposal = (
            f"{action.action}:{action.direction}:{action.source}:{action.signal_score:.0f}"
        )
        if self._last_proposal.get(key) == proposal:
            return  # already alerted this exact proposal
        self._last_proposal[key] = proposal

        verb = action.action.upper()
        inst = action.instrument or "?"
        direction = (action.direction or "").upper()
        reason = action.reason or "no reason given"
        # Translate code-style reasons into readable text
        if reason.startswith("hard_stop:"):
            detail = reason.split(":", 1)[1].strip()
            reason = f"Hard stop triggered ({detail})"
        msg = (
            f"*Trade suggestion* (not executed)\n"
            f"  {verb} {inst} {direction}\n"
            f"  {reason}"
        )
        ctx.alerts.append(Alert(
            severity="info",  # advisor is informational; user makes the call
            source=self.name,
            message=msg.strip(),
            data={
                "action": action.action,
                "instrument": action.instrument,
                "direction": action.direction,
                "slot_id": action.slot_id,
                "source": action.source,
                "signal_score": action.signal_score,
                "reason": action.reason,
                "execution_algo": action.execution_algo,
            },
        ))
        log.info("[advice] %s", msg)
