"""ArchitectIterator — drives the Architect Engine self-improvement pipeline.

Each tick (every 12h by default):
  1. Run mechanical pattern detection on autoresearch evaluations
  2. Generate fix proposals for recurring patterns
  3. Fire Telegram alerts for new findings/proposals

Kill switch: data/config/architect.json → enabled: false
Ships with enabled=false — zero production impact.
Registered in ALL tiers (read-only, no mutations to trading config).
Default interval: 12 hours (configurable). Zero AI calls. Zero API costs.
"""
from __future__ import annotations

import logging
import time

from cli.daemon.context import Alert, TickContext

log = logging.getLogger("daemon.architect")


class ArchitectIterator:
    name = "architect"

    def __init__(self):
        self._last_run: float = 0.0
        self._engine = None
        self._interval_s: float = 12 * 3600  # 12 hours default

    def on_start(self, ctx: TickContext) -> None:
        try:
            from engines.learning.architect_engine import ArchitectEngine
            self._engine = ArchitectEngine()
            if self._engine.enabled:
                self._interval_s = self._engine.interval_hours * 3600
                log.info("ArchitectIterator started — interval=%dh", self._engine.interval_hours)
            else:
                log.info("ArchitectIterator disabled — no-op")
        except Exception as e:
            log.warning("ArchitectIterator failed to start: %s", e)

    def on_stop(self) -> None:
        pass

    def tick(self, ctx: TickContext) -> None:
        if not self._engine or not self._engine.enabled:
            return

        now = time.monotonic()
        if now - self._last_run < self._interval_s:
            return
        self._last_run = now

        # Detect patterns (pure Python, zero AI)
        try:
            new_findings = self._engine.detect()
            if new_findings:
                # Generate proposals for new findings
                new_proposals = self._engine.hypothesize(new_findings)

                for f in new_findings:
                    ctx.alerts.append(Alert(
                        source="architect",
                        severity="info",
                        message=f"🔍 Architect finding: [{f.severity}] {f.description}",
                    ))

                for p in new_proposals:
                    ctx.alerts.append(Alert(
                        source="architect",
                        severity="warning",
                        message=(
                            f"📋 Architect proposal: {p.title}\n"
                            f"  → {p.description[:100]}\n"
                            f"  Review: /architect proposals"
                        ),
                    ))

        except Exception as e:
            log.error("Architect detection failed: %s", e)
