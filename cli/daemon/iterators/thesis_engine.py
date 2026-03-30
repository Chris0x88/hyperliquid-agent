"""ThesisEngineIterator — reads ThesisState from disk into TickContext every tick.

This is Layer 1 of the two-layer architecture. The AI scheduled task WRITES
thesis state files. This iterator READS them and injects into ctx.thesis_states
so the execution_engine can adapt sizing and behavior based on AI conviction.

Stale data safety: clamps conviction to 0.3 after 24h, warns at 6h.
"""
from __future__ import annotations

import logging
import time
from typing import Any

from cli.daemon.context import Alert, TickContext
from common.thesis import ThesisState, DEFAULT_THESIS_DIR

log = logging.getLogger("daemon.thesis_engine")

RELOAD_INTERVAL_S = 60   # reload thesis files every 60 seconds


class ThesisEngineIterator:
    """Reads AI-authored ThesisState files from disk into TickContext."""

    name = "thesis_engine"

    def __init__(self, thesis_dir: str = DEFAULT_THESIS_DIR):
        self._thesis_dir = thesis_dir
        self._last_reload: float = 0.0
        self._warned_stale: set = set()

    def on_start(self, ctx: TickContext) -> None:
        self._load_all(ctx)
        if not ctx.thesis_states:
            log.warning(
                "ThesisEngine: no thesis files found in %s — "
                "execution_engine will use conservative defaults until AI writes ThesisState",
                self._thesis_dir,
            )
            ctx.alerts.append(Alert(
                severity="warning",
                source=self.name,
                message=f"No thesis files in {self._thesis_dir} — execution running on defaults",
            ))
        else:
            log.info("ThesisEngine loaded %d thesis states: %s",
                     len(ctx.thesis_states), list(ctx.thesis_states.keys()))

    def on_stop(self) -> None:
        pass

    def tick(self, ctx: TickContext) -> None:
        now = time.monotonic()
        if now - self._last_reload < RELOAD_INTERVAL_S:
            return
        self._load_all(ctx)

    def _load_all(self, ctx: TickContext) -> None:
        self._last_reload = time.monotonic()
        states = ThesisState.load_all(self._thesis_dir)

        for market, state in states.items():
            effective_conv = state.effective_conviction()
            raw_conv = state.conviction

            # Stale warnings
            if state.is_very_stale and market not in self._warned_stale:
                log.warning(
                    "ThesisState for %s is %.1fh old — conviction clamped to %.2f (raw: %.2f)",
                    market, state.age_hours, effective_conv, raw_conv,
                )
                ctx.alerts.append(Alert(
                    severity="warning",
                    source=self.name,
                    message=f"Thesis for {market} is {state.age_hours:.1f}h old — needs refresh",
                    data={"market": market, "age_hours": state.age_hours, "effective_conviction": effective_conv},
                ))
                self._warned_stale.add(market)
            elif not state.is_very_stale and market in self._warned_stale:
                self._warned_stale.discard(market)
                log.info("ThesisState for %s refreshed (age: %.1fh)", market, state.age_hours)

            # Inject into context — execution_engine reads from here
            # We inject the raw object but execution_engine calls effective_conviction()
            ctx.thesis_states[market] = state

        # Log markets that dropped out (thesis file deleted)
        for market in list(ctx.thesis_states.keys()):
            if market not in states:
                log.info("ThesisState for %s removed from disk — removing from context", market)
                del ctx.thesis_states[market]

        if states:
            summary = " | ".join(
                f"{m.split(':')[-1]}={s.effective_conviction():.2f}({s.direction})"
                for m, s in states.items()
            )
            log.debug("ThesisEngine: %s", summary)
