"""ThesisChallengerIterator — watches for catalysts that invalidate thesis conditions.

Runs every 5 minutes (piggybacks on news_ingest cadence).
Pure Python — zero LLM calls. Pattern matching only.

When a new catalyst matches an invalidation condition in any thesis file,
fires a CRITICAL Telegram alert immediately.

Kill switch: data/config/thesis_challenger.json → enabled: false
Safe in all tiers (read-only, fires alerts only).
"""
from __future__ import annotations

import logging
import time

from cli.daemon.context import Alert, TickContext
from modules.thesis_challenger import ThesisChallengerEngine

log = logging.getLogger("daemon.thesis_challenger")

DEFAULT_CHECK_INTERVAL_S = 300  # 5 minutes


class ThesisChallengerIterator:
    name = "thesis_challenger"

    def __init__(self, check_interval: int = DEFAULT_CHECK_INTERVAL_S):
        self._engine = ThesisChallengerEngine()
        self._check_interval = check_interval
        self._last_check: float = 0.0
        self._started = False

    def on_start(self, ctx: TickContext) -> None:
        if not self._engine.enabled:
            log.info("ThesisChallengerIterator disabled via config — no-op")
            return
        # Full scan on startup to catch anything missed
        challenges = self._engine.scan(full=True)
        if challenges:
            for c in challenges:
                msg = self._engine.format_alert(c)
                ctx.alerts.append(Alert(
                    severity="critical",
                    source=self.name,
                    message=msg,
                ))
                log.warning(
                    "Thesis challenge on startup: %s — %s",
                    c.thesis_market, c.invalidation_condition,
                )
        self._started = True
        log.info(
            "ThesisChallengerIterator started — %d initial challenges",
            len(challenges),
        )

    def tick(self, ctx: TickContext) -> None:
        if not self._started or not self._engine.enabled:
            return

        now = time.monotonic()
        if now - self._last_check < self._check_interval:
            return
        self._last_check = now

        challenges = self._engine.scan(full=False)
        if not challenges:
            return

        for c in challenges:
            msg = self._engine.format_alert(c)
            ctx.alerts.append(Alert(
                severity="critical",
                source=self.name,
                message=msg,
            ))
            log.warning(
                "THESIS CHALLENGED: %s condition '%s' matched by '%s'",
                c.thesis_market,
                c.invalidation_condition,
                c.matched_headline,
            )
