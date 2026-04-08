"""SupplyLedgerIterator — sub-system 2 of the Oil Bot-Pattern Strategy.

Watches data/news/catalysts.jsonl (produced by news_ingest) for new
physical_damage / shipping_attack / chokepoint_blockade catalysts,
auto-extracts Disruption records, and periodically recomputes SupplyState.

Read-only: never places trades. Safe in all tiers.
Kill switch: data/config/supply_ledger.json → enabled: false
"""
from __future__ import annotations

import json
import logging
import time
from pathlib import Path

from cli.daemon.context import Alert, TickContext
from modules.supply_ledger import (
    Disruption,
    append_disruption,
    auto_extract_from_catalyst,
    compute_state,
    load_auto_extract_rules,
    read_disruptions,
    write_state_atomic,
)

log = logging.getLogger("daemon.supply_ledger")

DEFAULT_CONFIG_PATH = "data/config/supply_ledger.json"


class SupplyLedgerIterator:
    name = "supply_ledger"

    def __init__(self, config_path: str = DEFAULT_CONFIG_PATH):
        self._config_path = config_path
        self._config: dict = {}
        self._rules = []
        self._catalysts_mtime: float = 0.0
        self._last_recompute_mono: float = 0.0
        self._alerted_disruption_ids: set[str] = set()
        self._seen_catalyst_ids: set[str] = set()

    def on_start(self, ctx: TickContext) -> None:
        self._reload_config()
        if not self._config.get("enabled", False):
            log.info("SupplyLedgerIterator disabled — no-op")
            return
        log.info("SupplyLedgerIterator started — %d auto-extract rules", len(self._rules))

    def on_stop(self) -> None:
        pass

    def tick(self, ctx: TickContext) -> None:
        if not self._config.get("enabled", False):
            return
        # Body populated in Task 2.2

    def _reload_config(self) -> None:
        try:
            self._config = json.loads(Path(self._config_path).read_text())
        except (FileNotFoundError, json.JSONDecodeError) as e:
            log.warning("supply_ledger config unavailable (%s)", e)
            self._config = {"enabled": False}
            return
        try:
            self._rules = load_auto_extract_rules(self._config["auto_extract_rules"])
        except Exception as e:
            log.warning("supply_ledger auto_extract_rules unavailable (%s)", e)
            self._rules = []
