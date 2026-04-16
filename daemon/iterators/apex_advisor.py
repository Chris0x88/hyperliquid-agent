"""ApexAdvisorIterator — signal-driven APEX evaluator (advisor or live executor).

This is C3 from the 2026-04-07 connections audit. Reads radar_opportunities +
pulse_signals (populated by the radar and pulse iterators each tick), runs them
through ApexEngine, and either:

  - DRY-RUN mode (default): proposes actions as Telegram alerts, never executes
  - LIVE mode: converts ApexAction → OrderIntent and queues real orders

Mode is controlled by the kill switch at data/config/apex_executor.json:
  {"enabled": false}  → dry-run (default, safe)
  {"enabled": true}   → live execution on technical signals

The execution_engine (thesis-driven path) has its own kill switch at
data/config/execution_engine.json and defaults to disabled. This means
technical-signal execution is the DEFAULT path when you promote past WATCH tier.

Throttle: 60s. Finer than pulse (120s) and radar (300s) so no fresh signal is
missed. Heartbeat log on every cycle so operator can see the advisor is alive.
"""
from __future__ import annotations

import json
import logging
import os
import time
from decimal import Decimal
from typing import Dict, List, Optional

from daemon.context import Alert, OrderIntent, TickContext

log = logging.getLogger("daemon.apex_advisor")

# Throttle: run at most once per 60s. APEX proposes on signal cadence, not
# market tick cadence — there's no benefit to running it faster than the
# slowest input updates.
ADVISE_INTERVAL_S = 60

# Default APEX config knobs. 3 slots = same default as standalone_runner.
ADVISOR_MAX_SLOTS = 3

# Kill switch path — write {"enabled": true} to activate live execution.
_KILL_SWITCH = "data/config/apex_executor.json"


def _read_live_mode() -> bool:
    """Return True if apex_executor kill switch has enabled=true."""
    try:
        if os.path.exists(_KILL_SWITCH):
            with open(_KILL_SWITCH) as f:
                return bool(json.load(f).get("enabled", False))
    except Exception:
        pass
    return False  # safe default: dry-run only


class ApexAdvisorIterator:
    """Signal-driven APEX iterator — advisor by default, live executor when enabled."""

    name = "apex_advisor"

    def __init__(self) -> None:
        self._engine = None
        self._config = None
        self._last_advise: float = 0.0
        self._live: bool = False  # set in on_start from kill switch
        # Suppress repeated identical proposals (dry-run) or duplicate orders (live)
        self._last_proposal: Dict[str, str] = {}

    def on_start(self, ctx: TickContext) -> None:
        try:
            from engines.analysis.apex_config import ApexConfig
            from engines.analysis.apex_engine import ApexEngine
        except Exception as e:
            log.warning("ApexAdvisor: failed to import APEX modules: %s", e)
            return
        try:
            self._config = ApexConfig(max_slots=ADVISOR_MAX_SLOTS)
        except Exception as e:
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

        self._live = _read_live_mode()
        mode = "LIVE (signal-driven execution)" if self._live else "DRY-RUN (proposals only)"
        log.info(
            "ApexAdvisor started  max_slots=%d  interval=%ds  mode=%s",
            ADVISOR_MAX_SLOTS, ADVISE_INTERVAL_S, mode,
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
        from engines.analysis.apex_state import ApexState, ApexSlot

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

        inst = action.instrument or "?"
        direction = (action.direction or "").upper()
        reason = action.reason or "no reason given"
        if reason.startswith("hard_stop:"):
            detail = reason.split(":", 1)[1].strip()
            reason = f"Hard stop triggered ({detail})"

        if self._live:
            self._execute_action(ctx, action, inst, direction, reason)
        else:
            self._advise_action(ctx, action, inst, direction, reason)

    def _advise_action(self, ctx: TickContext, action, inst: str, direction: str, reason: str) -> None:
        """Dry-run: emit a Telegram alert only. No order queued."""
        verb = action.action.upper()
        msg = (
            f"*Trade signal* (not executed — apex_executor disabled)\n"
            f"  {verb} {inst} {direction}\n"
            f"  {reason}"
        )
        ctx.alerts.append(Alert(
            severity="info",
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
                "mode": "dry_run",
            },
        ))
        log.info("[signal/dry-run] %s %s %s — %s", action.action, inst, direction, reason)

    def _execute_action(self, ctx: TickContext, action, inst: str, direction: str, reason: str) -> None:
        """Live mode: convert ApexAction → OrderIntent and queue it."""
        from common.authority import is_agent_managed

        # Strip '-PERP' suffix for exchange instrument name
        exchange_inst = inst.replace("-PERP", "") if inst.endswith("-PERP") else inst

        if not is_agent_managed(exchange_inst):
            log.warning("ApexAdvisor: skipping %s — not agent-managed (check authority.json)", exchange_inst)
            return

        size = Decimal(str(round(action.size, 4))) if action.size > 0 else Decimal("0")

        if action.action == "enter":
            order_action = "buy" if action.direction == "long" else "sell"
            intent = OrderIntent(
                strategy_name=self.name,
                instrument=exchange_inst,
                action=order_action,
                size=size,
                meta={
                    "reason": reason,
                    "source": action.source,
                    "signal_score": action.signal_score,
                    "execution_algo": action.execution_algo,
                    "slot_id": action.slot_id,
                },
            )
        elif action.action == "exit":
            intent = OrderIntent(
                strategy_name=self.name,
                instrument=exchange_inst,
                action="close",
                size=size,
                reduce_only=True,
                meta={
                    "reason": reason,
                    "source": action.source,
                    "signal_score": action.signal_score,
                    "slot_id": action.slot_id,
                },
            )
        else:
            return  # noop — nothing to queue

        ctx.order_queue.append(intent)

        verb = action.action.upper()
        msg = (
            f"*Signal trade queued*\n"
            f"  {verb} {inst} {direction}\n"
            f"  {reason}\n"
            f"  score={action.signal_score:.0f}  src={action.source}"
        )
        ctx.alerts.append(Alert(
            severity="info",
            source=self.name,
            message=msg.strip(),
            data={
                "action": action.action,
                "instrument": exchange_inst,
                "direction": action.direction,
                "size": float(size),
                "slot_id": action.slot_id,
                "source": action.source,
                "signal_score": action.signal_score,
                "reason": action.reason,
                "mode": "live",
            },
        ))
        log.info("[signal/LIVE] %s %s %s size=%s — %s", action.action, exchange_inst, direction, size, reason)
