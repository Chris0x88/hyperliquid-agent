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

from daemon.context import Alert, TickContext
from engines.learning.news_engine import (
    Catalyst,
    Headline,
    dedupe_headlines,
    extract_catalysts,
    load_rules,
    parse_feed,
)
from engines.data import catalyst_bridge

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

        now_mono = time.monotonic()
        new_headlines: list[Headline] = []
        max_per_tick = int(self._config.get("max_headlines_per_tick", 50))

        for feed in self._feeds:
            name = feed["name"]
            interval = int(feed.get("poll_interval_s", self._config.get("default_poll_interval_s", 60)))
            if now_mono - self._last_poll.get(name, 0) < interval:
                continue
            self._last_poll[name] = now_mono
            try:
                resp = requests.get(feed["url"], timeout=10)
                if resp.status_code != 200:
                    log.warning("feed %s returned HTTP %d", name, resp.status_code)
                    continue
                entries = parse_feed(resp.text, source=name)
            except Exception as e:
                log.warning("feed %s fetch/parse failed: %s", name, e)
                continue
            new_headlines.extend(entries)
            if len(new_headlines) >= max_per_tick:
                break

        if not new_headlines:
            return

        # Load prior headline IDs from the JSONL for cross-tick dedup
        seen_ids = self._load_seen_headline_ids()
        fresh = [h for h in dedupe_headlines(new_headlines) if h.id not in seen_ids]
        if not fresh:
            return

        self._append_headlines_jsonl(fresh)
        catalysts = extract_catalysts(fresh, self._rules)
        if catalysts:
            self._append_catalysts_jsonl(catalysts)
            added = catalyst_bridge.persist(
                catalysts,
                self._config["external_catalyst_events_json"],
                severity_floor=int(self._config.get("severity_floor", 3)),
            )
            if added:
                log.info("news_ingest: appended %d catalysts above severity floor", added)
            self._maybe_alert(catalysts, ctx)

    # ------------------------------------------------------------------
    # JSONL writers + dedup
    # ------------------------------------------------------------------

    def _load_seen_headline_ids(self) -> set[str]:
        path = Path(self._config["headlines_jsonl"])
        if not path.exists():
            return set()
        seen: set[str] = set()
        try:
            with path.open("r") as f:
                for line in f:
                    try:
                        rec = json.loads(line)
                        seen.add(rec["id"])
                    except (json.JSONDecodeError, KeyError):
                        continue
        except OSError:
            pass
        return seen

    def _append_headlines_jsonl(self, headlines: list[Headline]) -> None:
        path = Path(self._config["headlines_jsonl"])
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a") as f:
            for h in headlines:
                f.write(json.dumps(_headline_to_dict(h), default=str) + "\n")

    def _append_catalysts_jsonl(self, catalysts: list[Catalyst]) -> None:
        path = Path(self._config["catalysts_jsonl"])
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a") as f:
            for c in catalysts:
                f.write(json.dumps(_catalyst_to_dict(c), default=str) + "\n")

    def _maybe_alert(self, catalysts: list[Catalyst], ctx: TickContext) -> None:
        alert_floor = int(self._config.get("alert_floor", 4))
        for c in catalysts:
            if c.severity < alert_floor:
                continue
            if c.id in self._alerted_catalyst_ids:
                continue
            self._alerted_catalyst_ids.add(c.id)
            direction = c.expected_direction or "?"
            ctx.alerts.append(Alert(
                severity="warning" if c.severity == 4 else "critical",
                source=self.name,
                message=f"NEW CATALYST sev={c.severity} {c.category}: {', '.join(c.instruments)} ({direction})",
                data={"category": c.category, "catalyst_id": c.id},
            ))

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


def _headline_to_dict(h: Headline) -> dict:
    return {
        "id": h.id,
        "source": h.source,
        "url": h.url,
        "title": h.title,
        "body_excerpt": h.body_excerpt,
        "published_at": h.published_at.isoformat(),
        "fetched_at": h.fetched_at.isoformat(),
    }


def _catalyst_to_dict(c: Catalyst) -> dict:
    return {
        "id": c.id,
        "headline_id": c.headline_id,
        "instruments": c.instruments,
        "event_date": c.event_date.isoformat(),
        "category": c.category,
        "severity": c.severity,
        "expected_direction": c.expected_direction,
        "rationale": c.rationale,
        "created_at": c.created_at.isoformat(),
    }
