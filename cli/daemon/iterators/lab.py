"""LabIterator — drives the Lab Engine strategy development pipeline.

Each tick:
  1. Check for experiments ready to advance (backtest → paper → graduated)
  2. Fire Telegram alerts on graduation events
  3. Collect paper trading signals for paper_trading experiments

Kill switch: data/config/lab.json → enabled: false
Ships with enabled=false — zero production impact.
Registered in ALL tiers (read-only + paper trading only, no real orders).
"""
from __future__ import annotations

import logging
import time
from pathlib import Path

from cli.daemon.context import Alert, TickContext

log = logging.getLogger("daemon.lab")

_CHECK_INTERVAL_S = 3600  # Check every hour


class LabIterator:
    name = "lab"

    def __init__(self):
        self._last_check: float = 0.0
        self._engine = None

    def on_start(self, ctx: TickContext) -> None:
        try:
            from engines.learning.lab_engine import LabEngine
            self._engine = LabEngine()
            if self._engine.enabled:
                log.info("LabIterator started — %d experiments tracked", len(self._engine._experiments))
            else:
                log.info("LabIterator disabled — no-op")
        except Exception as e:
            log.warning("LabIterator failed to start: %s", e)

    def on_stop(self) -> None:
        pass

    def tick(self, ctx: TickContext) -> None:
        if not self._engine or not self._engine.enabled:
            return

        now = time.monotonic()
        if now - self._last_check < _CHECK_INTERVAL_S:
            return
        self._last_check = now

        # Check paper-trading experiments for graduation
        for exp in self._engine._experiments:
            if exp.status == "paper_trading":
                graduated = self._engine.check_paper_graduation(exp.id)
                if graduated:
                    ctx.alerts.append(Alert(
                        source="lab",
                        severity="warning",
                        message=(
                            f"🧪 GRADUATED: {exp.strategy} on {exp.market} "
                            f"(sharpe={exp.paper_metrics.get('sharpe', 0):.2f}, "
                            f"WR={exp.paper_metrics.get('win_rate', 0):.0%}). "
                            f"Review with /lab status and /lab promote {exp.id}"
                        ),
                    ))
