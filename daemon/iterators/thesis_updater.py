"""ThesisUpdaterIterator — Haiku-powered news → thesis conviction adjustment.

Runs every 5 minutes. Reads new catalysts, classifies via Haiku,
applies tiered response with guardrails, updates thesis files.

CRITICAL news (Haiku 9-10) triggers INSTANT defensive mode or conviction boost.
No waiting for price confirmation on major events.

Kill switch: data/config/thesis_updater.json → enabled: false
Safe in all tiers (writes thesis files + audit log only).
"""
from __future__ import annotations

import json
import logging
import time
from pathlib import Path

from daemon.context import Alert, TickContext
from trading.thesis.updater import ThesisUpdaterEngine, HaikuClassification

log = logging.getLogger("daemon.thesis_updater")

DEFAULT_CHECK_INTERVAL_S = 300  # 5 minutes


class ThesisUpdaterIterator:
    name = "thesis_updater"

    def __init__(self, check_interval: int = DEFAULT_CHECK_INTERVAL_S):
        self._engine = ThesisUpdaterEngine()
        self._check_interval = check_interval
        self._last_check: float = 0.0
        self._started = False
        self._haiku_available = False

    def _setup_haiku(self) -> None:
        """Set up the Haiku call function using existing Anthropic auth."""
        try:
            from telegram.agent import _call_anthropic
            def call_haiku(messages):
                resp = _call_anthropic(messages, model_override="claude-haiku-4-5")
                return resp.get("content", "")
            self._engine._call_haiku = call_haiku
            self._haiku_available = True
            log.info("Haiku classifier available via Anthropic session token")
        except ImportError:
            log.warning("telegram_agent not available — Haiku classifier disabled")
            self._haiku_available = False

    def on_start(self, ctx: TickContext) -> None:
        self._engine.reload_config()
        if not self._engine.enabled:
            log.info("ThesisUpdaterIterator disabled via config — no-op")
            return

        self._setup_haiku()
        if not self._haiku_available:
            log.warning("ThesisUpdaterIterator started but Haiku unavailable")
            return

        # Load existing audit IDs to avoid reprocessing
        self._engine.load_audit_ids()

        # Set catalyst offset to current end (don't reprocess old catalysts)
        self._engine.load_all_catalysts()

        self._started = True
        log.info("ThesisUpdaterIterator started — Haiku classifier active")

    def tick(self, ctx: TickContext) -> None:
        if not self._started or not self._engine.enabled or not self._haiku_available:
            return

        now = time.monotonic()
        if now - self._last_check < self._check_interval:
            return
        self._last_check = now

        # Reload config in case kill switch changed
        self._engine.reload_config()
        if not self._engine.enabled:
            return

        # Get new catalysts
        catalysts = self._engine.load_new_catalysts()
        if not catalysts:
            return

        # Get price data from context if available
        price_data = self._extract_price_data(ctx)

        for catalyst in catalysts:
            cat_id = catalyst.get("id", "")

            # Skip if already processed
            if cat_id in self._engine._processed_ids:
                continue

            # Skip if in cooldown
            category = catalyst.get("category", "")
            if self._engine.is_in_cooldown(category):
                log.debug("Skipping catalyst %s — category %s in cooldown", cat_id, category)
                continue

            # Load headline
            headline_id = catalyst.get("headline_id", "")
            headline = self._engine.load_headline(headline_id)

            # Classify via Haiku
            classification = self._engine.classify_catalyst(catalyst, headline)
            if not classification:
                log.warning("Failed to classify catalyst %s", cat_id)
                self._engine._processed_ids.add(cat_id)
                continue

            # Process and get conviction changes
            changes = self._engine.process_catalyst(
                catalyst, headline, classification, price_data,
            )

            # Fire alerts for any changes
            for change in changes:
                msg = self._engine.format_alert(change)
                level = "critical" if change.tier == "CRITICAL" else (
                    "warning" if change.tier == "MAJOR" else "info"
                )
                ctx.alerts.append(Alert(
                    severity=level,
                    source=self.name,
                    message=msg,
                ))

                # If defensive mode, also signal Guard override
                if change.defensive_mode and change.guard_override:
                    ctx.alerts.append(Alert(
                        severity="critical",
                        source=self.name,
                        message=(
                            f"⚡ GUARD OVERRIDE — {change.market}\n"
                            f"Forcing Phase 2 (lock-the-bag) with tight retrace.\n"
                            f"Trigger: {change.headline}"
                        ),
                    ))

                # Go-flat alert
                go_flat = self._engine._config.get("go_flat_threshold", 0.10)
                if change.conviction_after < go_flat:
                    ctx.alerts.append(Alert(
                        severity="critical",
                        source=self.name,
                        message=(
                            f"🔴 CONVICTION CRITICALLY LOW — {change.market}\n"
                            f"Conviction at {change.conviction_after:.2f} "
                            f"(below {go_flat} threshold).\n"
                            f"Consider going FLAT. Review thesis immediately."
                        ),
                    ))

                log.info(
                    "Conviction updated: %s %.2f → %.2f (tier=%s, headline='%s')",
                    change.market,
                    change.conviction_before,
                    change.conviction_after,
                    change.tier,
                    change.headline[:60],
                )

    def _extract_price_data(self, ctx: TickContext) -> dict:
        """Extract recent price data from TickContext for tier adjustment."""
        price_data = {}
        # Try to get price change and volume from context snapshots
        snapshots = getattr(ctx, "market_snapshots", {})
        for market, snap in snapshots.items():
            if isinstance(snap, dict):
                price_data[market] = {
                    "price_change_pct": abs(snap.get("change_24h_pct", 0.0)),
                    "volume_ratio": snap.get("volume_ratio", 1.0),
                }
        return price_data
