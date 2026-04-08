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
        self._reload_config()
        if not self._config.get("enabled", False):
            return

        catalysts_path_str = self._config.get("catalysts_jsonl", "data/news/catalysts.jsonl")
        catalysts_path = Path(catalysts_path_str)

        # mtime-watch catalysts.jsonl
        if catalysts_path.exists():
            try:
                mtime = catalysts_path.stat().st_mtime
            except OSError:
                mtime = 0.0
            if mtime > self._catalysts_mtime:
                self._catalysts_mtime = mtime
                self._process_catalysts_file(catalysts_path, ctx)

        # Periodic recompute
        now_mono = time.monotonic()
        interval = int(self._config.get("recompute_interval_s", 300))
        if self._last_recompute_mono == 0.0 or (now_mono - self._last_recompute_mono) >= interval:
            self._recompute_state()
            self._last_recompute_mono = now_mono

    def _process_catalysts_file(self, path: Path, ctx: TickContext) -> None:
        if not self._config.get("auto_extract", True):
            return
        try:
            with path.open("r") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        cat = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    cat_id = cat.get("id")
                    if not cat_id or cat_id in self._seen_catalyst_ids:
                        continue
                    self._seen_catalyst_ids.add(cat_id)

                    disruption = auto_extract_from_catalyst(cat, self._rules)
                    if disruption is None:
                        continue

                    # Dedupe against existing disruptions.jsonl
                    existing_ids = {d.id for d in read_disruptions(self._config["disruptions_jsonl"])}
                    if disruption.id in existing_ids:
                        continue

                    append_disruption(self._config["disruptions_jsonl"], disruption)
                    self._maybe_alert(disruption, ctx)
                    # Force recompute on next tick boundary
                    self._last_recompute_mono = 0.0
        except OSError as e:
            log.warning("supply_ledger: failed reading %s: %s", path, e)

    def _recompute_state(self) -> None:
        rows = read_disruptions(self._config["disruptions_jsonl"])
        state = compute_state(rows)
        write_state_atomic(self._config["state_json"], state)

    def _maybe_alert(self, d: Disruption, ctx: TickContext) -> None:
        if d.id in self._alerted_disruption_ids:
            return
        if d.facility_type not in ("chokepoint", "refinery"):
            return
        self._alerted_disruption_ids.add(d.id)
        ctx.alerts.append(Alert(
            severity="info",
            source=self.name,
            message=f"NEW SUPPLY DISRUPTION {d.facility_type}: {d.facility_name} ({d.region})",
            data={"disruption_id": d.id, "source": d.source},
        ))

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
