"""ThesisEngineIterator — reads ThesisState from disk into TickContext every tick.

This is Layer 1 of the two-layer architecture. The AI scheduled task WRITES
thesis state files. This iterator READS them and injects into ctx.thesis_states
so the execution_engine can adapt sizing and behavior based on AI conviction.

Staleness handling is delegated to ThesisState.effective_conviction():
  - < 7 days: full conviction (thesis can hold for weeks/months)
  - 7-14 days: linear taper toward 0.3
  - > 14 days: clamp to 0.3 (defensive)
  - > 7 days: weekly Telegram alert to review
"""
from __future__ import annotations

import logging
import time
from typing import Any

from cli.daemon.context import Alert, TickContext
from common.thesis import ThesisState, DEFAULT_THESIS_DIR

log = logging.getLogger("daemon.thesis_engine")

RELOAD_INTERVAL_S = 60   # reload thesis files every 60 seconds

# Alert when thesis needs review — but thesis can be valid for months.
# ThesisState.effective_conviction() handles the actual tapering.
_REVIEW_AGE_H = 168.0       # 7 days — first alert
_REALERT_INTERVAL_S = 7 * 86400  # re-alert weekly (not hourly)


class ThesisEngineIterator:
    """Reads AI-authored ThesisState files from disk into TickContext."""

    name = "thesis_engine"

    def __init__(self, thesis_dir: str = DEFAULT_THESIS_DIR):
        self._thesis_dir = thesis_dir
        self._last_reload: float = 0.0
        self._alerted: dict = {}     # market -> last_alert_time

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
        now = time.time()

        for market, state in states.items():
            age_h = state.age_hours
            effective_conv = state.effective_conviction()

            # No manual clamping — ThesisState.effective_conviction() handles
            # staleness tapering (7d linear taper, 14d defensive clamp).
            # Thesis can be valid for months; only log when tapering kicks in.
            if state.is_stale:
                log.debug(
                    "ThesisState for %s is %.0fh old — effective conviction: %.2f (tapered from %.2f)",
                    market, age_h, effective_conv, state.conviction,
                )

            # Weekly review reminder for theses older than 7 days
            if age_h > _REVIEW_AGE_H:
                last_alert = self._alerted.get(market, 0)
                if now - last_alert >= _REALERT_INTERVAL_S:
                    display = market.replace("xyz:", "")
                    days = age_h / 24
                    ctx.alerts.append(Alert(
                        severity="info",
                        source=self.name,
                        message=(
                            f"Thesis for {display} is {days:.0f} days old — "
                            f"conviction={state.conviction:.2f} "
                            f"(effective={effective_conv:.2f}). "
                            f"Review with /thesis if conditions changed."
                        ),
                        data={"market": market, "age_hours": age_h,
                              "effective_conviction": effective_conv},
                    ))
                    self._alerted[market] = now
            elif market in self._alerted:
                del self._alerted[market]
                log.info("ThesisState for %s refreshed (age: %.1fh)", market, age_h)

            # Inject into context — execution_engine reads from here
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
