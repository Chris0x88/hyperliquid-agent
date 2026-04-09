"""ArchitectIterator — self-improvement loop in the daemon tick loop.

Runs every 30 minutes (offset 15 min from autoresearch so they don't collide).
Reads evaluation data, detects patterns, generates hypotheses, and creates
proposals for human approval.

This closes the loop from "detect problem" → "propose fix" that was previously
an open gap in the system.
"""
from __future__ import annotations

import logging
import time

from cli.daemon.context import Alert, TickContext

log = logging.getLogger("daemon.architect")

ARCHITECT_INTERVAL_S = 1800  # 30 minutes
INITIAL_DELAY_S = 900        # Start 15 min after daemon to let autoresearch run first


class ArchitectIterator:
    """Self-improvement loop running in the daemon."""

    name = "architect"

    def __init__(self):
        self._last_tick: float = 0.0
        self._start_time: float = 0.0
        self._engine = None

    def on_start(self, ctx: TickContext) -> None:
        from modules.architect_engine import ArchitectEngine
        self._engine = ArchitectEngine()
        self._start_time = time.monotonic()
        pending = self._engine.get_pending()
        log.info("ArchitectIterator started — %d pending proposals", len(pending))

    def on_stop(self) -> None:
        pass

    def tick(self, ctx: TickContext) -> None:
        now = time.monotonic()

        # Initial delay: wait for autoresearch to produce data first
        if now - self._start_time < INITIAL_DELAY_S:
            return

        if now - self._last_tick < ARCHITECT_INTERVAL_S:
            return
        self._last_tick = now

        if self._engine is None:
            return

        try:
            events = self._engine.tick()

            for event in events:
                if event.get("type") == "new_proposal":
                    ctx.alerts.append(Alert(
                        severity="info",
                        source="architect",
                        message=(
                            f"NEW PROPOSAL: {event.get('change', '?')}\n"
                            f"Finding: {event.get('finding', '?')[:100]}\n"
                            f"Rationale: {event.get('rationale', '?')[:100]}"
                        ),
                    ))
                    log.info("Architect: new proposal — %s", event.get("change"))

        except Exception as e:
            log.error("ArchitectIterator tick failed: %s", e)
