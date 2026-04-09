"""LabIterator — runs the strategy development pipeline in the daemon tick loop.

Runs every 15 minutes (900s). Progresses experiments through stages:
  discovery → hypothesis → backtest → paper_trade → graduated

Sends Telegram alerts when experiments graduate or need attention.
"""
from __future__ import annotations

import logging
import time

from cli.daemon.context import Alert, TickContext

log = logging.getLogger("daemon.lab")

LAB_INTERVAL_S = 900  # 15 minutes


class LabIterator:
    """Strategy development pipeline running in the daemon."""

    name = "lab"

    def __init__(self):
        self._last_tick: float = 0.0
        self._engine = None

    def on_start(self, ctx: TickContext) -> None:
        from modules.lab_engine import LabEngine
        self._engine = LabEngine()
        active = self._engine.get_active()
        graduated = self._engine.get_graduated()
        log.info("LabIterator started — %d active, %d graduated experiments",
                 len(active), len(graduated))

    def on_stop(self) -> None:
        pass

    def tick(self, ctx: TickContext) -> None:
        now = time.monotonic()
        if now - self._last_tick < LAB_INTERVAL_S:
            return
        self._last_tick = now

        if self._engine is None:
            return

        try:
            events = self._engine.tick()

            for event in events:
                if event.get("type") == "stage_change" and event.get("stage") == "paper_trade":
                    ctx.alerts.append(Alert(
                        severity="info",
                        source="lab",
                        message=event.get("message", f"Experiment advanced to paper_trade"),
                    ))
                elif event.get("type") == "backtest_complete":
                    metrics = event.get("metrics", {})
                    log.info("Lab backtest: %s sharpe=%.2f wr=%.1f%%",
                             event.get("id"), metrics.get("sharpe_ratio", 0),
                             metrics.get("win_rate", 0))

            # Check for graduations
            for exp in self._engine.get_graduated():
                if exp.updated_ts > (time.time() * 1000 - LAB_INTERVAL_S * 1000):
                    ctx.alerts.append(Alert(
                        severity="info",
                        source="lab",
                        message=f"GRADUATED: {exp.market}:{exp.strategy} "
                                f"(score={exp.graduation_score:.2f}) — ready for production",
                    ))

        except Exception as e:
            log.error("LabIterator tick failed: %s", e)
