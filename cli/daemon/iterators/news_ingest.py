"""NewsIngestIterator — polls RSS feeds + iCal calendars, writes catalysts.

Spec: docs/plans/OIL_BOT_PATTERN_01_NEWS_INGESTION.md
Parent: docs/plans/OIL_BOT_PATTERN_SYSTEM.md

This iterator is additive and read-only (no trades). It is safe in all tiers.
Kill switch: data/config/news_ingest.json → enabled: false.
"""
from __future__ import annotations

import json
import logging
import time
from dataclasses import asdict
from pathlib import Path
from typing import Optional

import requests
import yaml

from cli.daemon.context import Alert, TickContext
from modules.news_engine import (
    Catalyst,
    Headline,
    dedupe_headlines,
    extract_catalysts,
    load_rules,
    parse_feed,
)
from modules import catalyst_bridge

log = logging.getLogger("daemon.news_ingest")

DEFAULT_CONFIG_PATH = "data/config/news_ingest.json"
DEFAULT_FEEDS_PATH = "data/config/news_feeds.yaml"
DEFAULT_RULES_PATH = "data/config/news_rules.yaml"


class NewsIngestIterator:
    name = "news_ingest"

    def __init__(
        self,
        config_path: str = DEFAULT_CONFIG_PATH,
        feeds_path: str = DEFAULT_FEEDS_PATH,
        rules_path: str = DEFAULT_RULES_PATH,
    ):
        self._config_path = config_path
        self._feeds_path = feeds_path
        self._rules_path = rules_path
        self._config: dict = {}
        self._feeds: list[dict] = []
        self._rules = []
        self._last_poll: dict[str, float] = {}  # feed name → last poll monotonic
        self._alerted_catalyst_ids: set[str] = set()

    def on_start(self, ctx: TickContext) -> None:
        self._reload_config()
        if not self._config.get("enabled", False):
            log.info("NewsIngestIterator disabled via config — no-op")
            return
        log.info("NewsIngestIterator started — %d feeds, %d rules", len(self._feeds), len(self._rules))

    def on_stop(self) -> None:
        pass

    def tick(self, ctx: TickContext) -> None:
        self._reload_config_if_changed()
        if not self._config.get("enabled", False):
            return
        # Phases 4.2+ fill in the polling, dedup, extract, write, alert pipeline.

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _reload_config(self) -> None:
        try:
            self._config = json.loads(Path(self._config_path).read_text())
        except (FileNotFoundError, json.JSONDecodeError) as e:
            log.warning("news_ingest config unavailable (%s) — iterator disabled", e)
            self._config = {"enabled": False}
            return
        try:
            feeds_doc = yaml.safe_load(Path(self._feeds_path).read_text())
            self._feeds = [f for f in feeds_doc.get("feeds", []) if f.get("enabled", True)]
        except Exception as e:
            log.warning("news_ingest feeds unavailable (%s)", e)
            self._feeds = []
        try:
            self._rules = load_rules(self._rules_path)
        except Exception as e:
            log.warning("news_ingest rules unavailable (%s) — no tagging", e)
            self._rules = []

    def _reload_config_if_changed(self) -> None:
        # V1: full reload every tick is cheap enough with ≤10 feeds and ≤50 rules.
        # V2: mtime-watch for changes.
        self._reload_config()
