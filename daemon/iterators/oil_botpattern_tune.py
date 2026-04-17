"""OilBotPatternTuneIterator — sub-system 6 layer L1 bounded auto-tune.

Spec: docs/plans/OIL_BOT_PATTERN_06_SELF_TUNE_HARNESS.md

Watches closed oil_botpattern trades (from data/research/journal.jsonl)
plus the decision journal (data/strategy/oil_botpattern_journal.jsonl).
Each eligible tick:

  1. Reads the last N closed oil_botpattern trades (window_size).
  2. Reads the last N decisions from the decision journal.
  3. Reads the audit log to build a per-param rate-limit index.
  4. Calls modules.oil_botpattern_tune.compute_proposals().
  5. If any proposals are returned, applies them atomically to
     data/config/oil_botpattern.json and appends audit records to
     data/strategy/oil_botpattern_tune_audit.jsonl.

Kill switch: data/config/oil_botpattern_tune.json → enabled: false.
Ships with enabled=false — zero production impact on first deploy.

Registered in REBALANCE + OPPORTUNISTIC tiers only. NOT in WATCH.
Rationale: L1 mutates oil_botpattern.json. oil_botpattern is only
active in those tiers, so running L1 in WATCH has no value and only
expands blast radius.

This iterator does NOT place trades, emit OrderIntents, or call any
external APIs. It only reads the two journals and atomically rewrites
a single config file.
"""
from __future__ import annotations

import json
import logging
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from daemon.context import Alert, TickContext
from trading.oil.tune import (
    TuneAuditRecord,
    apply_proposals,
    audit_to_dict,
    build_audit_index,
    compute_proposals,
    parse_bounds,
)

log = logging.getLogger("daemon.oil_botpattern_tune")

DEFAULT_CONFIG_PATH = "data/config/oil_botpattern_tune.json"


class OilBotPatternTuneIterator:
    name = "oil_botpattern_tune"

    def __init__(self, config_path: str = DEFAULT_CONFIG_PATH):
        self._config_path = Path(config_path)
        self._config: dict = {}
        self._last_poll_mono: float = 0.0

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def on_start(self, ctx: TickContext) -> None:
        self._reload_config()
        if not self._config.get("enabled", False):
            log.info("OilBotPatternTuneIterator disabled — no-op")
            return
        log.info(
            "OilBotPatternTuneIterator started — window=%d min_sample=%d rate_limit=%dh",
            int(self._config.get("window_size", 20)),
            int(self._config.get("min_sample", 5)),
            int(self._config.get("min_rate_limit_hours", 24)),
        )

    def on_stop(self) -> None:
        pass

    # ------------------------------------------------------------------
    # Tick
    # ------------------------------------------------------------------

    def tick(self, ctx: TickContext) -> None:
        self._reload_config()
        if not self._config.get("enabled", False):
            return

        interval = int(self._config.get("tick_interval_s", 300))
        now_mono = time.monotonic()
        if self._last_poll_mono != 0.0 and (now_mono - self._last_poll_mono) < interval:
            return
        self._last_poll_mono = now_mono

        now = datetime.now(tz=timezone.utc)

        # Parse bounds first so we fail fast on a bad config
        try:
            bounds = parse_bounds(self._config.get("bounds", {}))
        except ValueError as e:
            log.warning("oil_botpattern_tune: bad bounds config: %s", e)
            return
        if not bounds:
            log.warning("oil_botpattern_tune: no bounds configured — no-op")
            return

        strategy_cfg_path = self._config.get(
            "strategy_config_path", "data/config/oil_botpattern.json"
        )
        try:
            strategy_cfg = json.loads(Path(strategy_cfg_path).read_text())
        except (FileNotFoundError, json.JSONDecodeError) as e:
            log.warning("oil_botpattern_tune: cannot read %s: %s", strategy_cfg_path, e)
            return

        window_size = int(self._config.get("window_size", 20))
        trades = self._load_recent_closed_trades(window_size)
        decisions = self._load_recent_decisions(window_size)
        audit_rows = self._load_audit_rows()
        audit_index = build_audit_index(audit_rows)

        proposals = compute_proposals(
            current_config=strategy_cfg,
            bounds=bounds,
            trades=trades,
            decisions=decisions,
            audit_index=audit_index,
            now=now,
            min_sample=int(self._config.get("min_sample", 5)),
            rel_step_max=float(self._config.get("rel_step_max", 0.05)),
            rate_limit_hours=int(self._config.get("min_rate_limit_hours", 24)),
        )

        if not proposals:
            return

        new_cfg, audits = apply_proposals(strategy_cfg, proposals)
        try:
            self._write_strategy_config_atomic(Path(strategy_cfg_path), new_cfg)
        except OSError as e:
            log.warning("oil_botpattern_tune: failed to write %s: %s", strategy_cfg_path, e)
            return

        try:
            self._append_audits(audits)
        except OSError as e:
            log.warning("oil_botpattern_tune: failed to append audit log: %s", e)
            # Config already mutated — intentional. The audit trail is best-effort;
            # a filesystem issue shouldn't block the nudge that already succeeded.
            # Next tick will re-read the config and include the new state.

        for rec in audits:
            log.info(
                "oil_botpattern_tune: nudged %s %.6g → %.6g (%s)",
                rec.param, float(rec.old_value), float(rec.new_value), rec.reason,
            )
            ctx.alerts.append(Alert(
                severity="info", source=self.name,
                message=(
                    f"oil_botpattern_tune nudged {rec.param}: "
                    f"{rec.old_value} → {rec.new_value} ({rec.reason})"
                ),
                data={
                    "param": rec.param,
                    "old_value": rec.old_value,
                    "new_value": rec.new_value,
                    "reason": rec.reason,
                    "sample_size": rec.stats_sample_size,
                },
            ))

    # ------------------------------------------------------------------
    # Config reload
    # ------------------------------------------------------------------

    def _reload_config(self) -> None:
        try:
            self._config = json.loads(self._config_path.read_text())
        except (FileNotFoundError, json.JSONDecodeError) as e:
            log.warning("oil_botpattern_tune config unavailable (%s)", e)
            self._config = {"enabled": False}

    # ------------------------------------------------------------------
    # Input loaders
    # ------------------------------------------------------------------

    def _load_recent_closed_trades(self, window_size: int) -> list[dict]:
        """Last `window_size` closed oil_botpattern trades from main journal.

        When Sub-5 is in decisions_only=true (shadow mode), also appends rows
        from the shadow-trades JSONL so L1 has learning signal. Each shadow row
        is tagged source="shadow". Shadow rows are NOT appended when
        decisions_only=false to avoid double-counting live positions.
        """
        path = Path(self._config.get(
            "main_journal_jsonl", "data/research/journal.jsonl"
        ))
        out: list[dict] = []
        if path.exists():
            try:
                with path.open("r") as f:
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            row = json.loads(line)
                        except json.JSONDecodeError:
                            continue
                        if row.get("strategy_id") != "oil_botpattern":
                            continue
                        if row.get("status") != "closed":
                            continue
                        out.append(row)
            except OSError as e:
                log.warning("oil_botpattern_tune: failed to read %s: %s", path, e)

        out.extend(self._load_shadow_trades())
        return out[-window_size:] if window_size > 0 else out

    def _load_shadow_trades(self) -> list[dict]:
        """Append shadow-mode closed trades when Sub-5 is in decisions_only=true.

        Reads Sub-5's config to check the decisions_only gate. Maps shadow-trade
        fields to canonical closed-trade fields so compute_proposals sees a
        uniform schema. Each row carries source="shadow" for attribution.
        """
        strategy_cfg_path = Path(self._config.get(
            "strategy_config_path", "data/config/oil_botpattern.json"
        ))
        try:
            strategy_cfg = json.loads(strategy_cfg_path.read_text())
        except (FileNotFoundError, json.JSONDecodeError):
            return []
        if not strategy_cfg.get("decisions_only", False):
            return []

        shadow_path = Path(strategy_cfg.get(
            "shadow_trades_jsonl", "data/strategy/oil_botpattern_shadow_trades.jsonl"
        ))
        if not shadow_path.exists():
            return []

        out: list[dict] = []
        try:
            with shadow_path.open("r") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        raw = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    # Map shadow fields → canonical closed-trade schema
                    row = dict(raw)
                    row.setdefault("strategy_id", "oil_botpattern")
                    row.setdefault("status", "closed")
                    row.setdefault("source", "shadow")
                    if "exit_reason" in row and "close_reason" not in row:
                        row["close_reason"] = row["exit_reason"]
                    if "exit_ts" in row and "close_ts" not in row:
                        row["close_ts"] = row["exit_ts"]
                    out.append(row)
        except OSError as e:
            log.warning("oil_botpattern_tune: failed to read shadow trades %s: %s",
                        shadow_path, e)
        return out

    def _load_recent_decisions(self, window_size: int) -> list[dict]:
        path = Path(self._config.get(
            "decision_journal_jsonl",
            "data/strategy/oil_botpattern_journal.jsonl",
        ))
        if not path.exists():
            return []
        out: list[dict] = []
        try:
            with path.open("r") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        out.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue
        except OSError as e:
            log.warning("oil_botpattern_tune: failed to read %s: %s", path, e)
            return []
        # Decision-journal window should at least cover window_size, but also
        # capture recent decisions that blocked (didn't close) — use a larger
        # multiplier to make sure the short_catalyst_sev gate has input.
        multiplier = max(window_size * 5, 100)
        return out[-multiplier:] if multiplier > 0 else out

    def _load_audit_rows(self) -> list[dict]:
        path = Path(self._config.get(
            "audit_jsonl", "data/strategy/oil_botpattern_tune_audit.jsonl"
        ))
        if not path.exists():
            return []
        rows: list[dict] = []
        try:
            with path.open("r") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        rows.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue
        except OSError as e:
            log.warning("oil_botpattern_tune: failed to read audit %s: %s", path, e)
            return []
        return rows

    # ------------------------------------------------------------------
    # Atomic writes
    # ------------------------------------------------------------------

    @staticmethod
    def _write_strategy_config_atomic(path: Path, cfg: dict) -> None:
        """Atomic rewrite preserving key order and indentation."""
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(cfg, indent=2, sort_keys=False) + "\n")
        os.replace(tmp, path)

    def _append_audits(self, audits: list[TuneAuditRecord]) -> None:
        path = Path(self._config.get(
            "audit_jsonl", "data/strategy/oil_botpattern_tune_audit.jsonl"
        ))
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a") as f:
            for rec in audits:
                f.write(json.dumps(audit_to_dict(rec)) + "\n")
