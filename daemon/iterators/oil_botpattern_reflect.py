"""OilBotPatternReflectIterator — sub-system 6 layer L2 weekly proposals.

Spec: docs/plans/OIL_BOT_PATTERN_06_SELF_TUNE_HARNESS.md

Runs WEEKLY (first tick where now - last_run_at ≥ min_run_interval_days).
Reads the closed-trade stream + decision journal, runs the L2 detection
rules, appends new StructuralProposal records to a proposals JSONL, and
fires a Telegram warning alert listing the new proposal IDs.

L2 NEVER auto-applies. All proposals start `status="pending"`. Chris
reviews via /selftuneproposals and taps /selftuneapprove <id> or
/selftunereject <id>. The approval/rejection handlers live in
cli/telegram_bot.py, not this iterator.

Kill switch: data/config/oil_botpattern_reflect.json → enabled: false.
Ships with enabled=false.

Registered in REBALANCE + OPPORTUNISTIC tiers only. NOT in WATCH.
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from daemon.context import Alert, TickContext
from modules.oil_botpattern_reflect import (
    compute_weekly_proposals,
    proposal_from_dict,
    proposal_to_dict,
)

log = logging.getLogger("daemon.oil_botpattern_reflect")

DEFAULT_CONFIG_PATH = "data/config/oil_botpattern_reflect.json"


class OilBotPatternReflectIterator:
    name = "oil_botpattern_reflect"

    def __init__(self, config_path: str = DEFAULT_CONFIG_PATH):
        self._config_path = Path(config_path)
        self._config: dict = {}

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def on_start(self, ctx: TickContext) -> None:
        self._reload_config()
        if not self._config.get("enabled", False):
            log.info("OilBotPatternReflectIterator disabled — no-op")
            return
        log.info(
            "OilBotPatternReflectIterator started — window=%dd interval=%dd",
            int(self._config.get("window_days", 7)),
            int(self._config.get("min_run_interval_days", 7)),
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

        now = datetime.now(tz=timezone.utc)
        state = self._load_state(now)
        if not self._is_run_due(state, now):
            return

        window_days = int(self._config.get("window_days", 7))
        min_sample = int(self._config.get("min_sample_per_rule", 5))

        trades = self._load_closed_trades()
        decisions = self._load_decisions()

        next_id = int(state.get("last_proposal_id", 0)) + 1
        new_proposals = compute_weekly_proposals(
            trades=trades,
            decisions=decisions,
            window_days=window_days,
            min_sample_per_rule=min_sample,
            now=now,
            next_id=next_id,
        )

        # Always update last_run_at even if no proposals — that's the point
        # of a "we looked and there was nothing" run.
        state["last_run_at"] = now.isoformat()
        if new_proposals:
            state["last_proposal_id"] = max(p.id for p in new_proposals)

        try:
            self._write_state_atomic(state)
        except OSError as e:
            log.warning("oil_botpattern_reflect: failed to write state: %s", e)
            return

        if not new_proposals:
            log.info("oil_botpattern_reflect: weekly scan — no proposals emitted")
            return

        try:
            self._append_proposals(new_proposals)
        except OSError as e:
            log.warning("oil_botpattern_reflect: failed to append proposals: %s", e)
            return

        ids_str = ", ".join(f"#{p.id}" for p in new_proposals)
        log.info(
            "oil_botpattern_reflect: weekly scan emitted %d proposals (%s)",
            len(new_proposals), ids_str,
        )
        ctx.alerts.append(Alert(
            severity="warning", source=self.name,
            message=(
                f"oil_botpattern_reflect: {len(new_proposals)} new structural "
                f"proposal(s) pending review ({ids_str}). "
                f"Run /selftuneproposals to review."
            ),
            data={
                "count": len(new_proposals),
                "ids": [p.id for p in new_proposals],
                "types": [p.type for p in new_proposals],
            },
        ))

    # ------------------------------------------------------------------
    # Cadence check
    # ------------------------------------------------------------------

    def _is_run_due(self, state: dict, now: datetime) -> bool:
        last_run_iso = state.get("last_run_at")
        if not last_run_iso:
            return True
        try:
            last_run = datetime.fromisoformat(last_run_iso)
            if last_run.tzinfo is None:
                last_run = last_run.replace(tzinfo=timezone.utc)
        except ValueError:
            return True
        interval_days = int(self._config.get("min_run_interval_days", 7))
        return (now - last_run) >= timedelta(days=interval_days)

    # ------------------------------------------------------------------
    # Config + state
    # ------------------------------------------------------------------

    def _reload_config(self) -> None:
        try:
            self._config = json.loads(self._config_path.read_text())
        except (FileNotFoundError, json.JSONDecodeError) as e:
            log.warning("oil_botpattern_reflect config unavailable (%s)", e)
            self._config = {"enabled": False}

    def _load_state(self, now: datetime) -> dict:
        path = Path(self._config.get(
            "state_json", "data/strategy/oil_botpattern_reflect_state.json"
        ))
        if not path.exists():
            # Seed: set last_run_at to one interval ago so first tick runs.
            # Without seeding, an unset last_run_at also triggers a run
            # (via _is_run_due), so this is equivalent. Keep explicit for
            # clarity.
            return {"last_run_at": None, "last_proposal_id": 0}
        try:
            return json.loads(path.read_text())
        except (OSError, json.JSONDecodeError):
            log.warning("oil_botpattern_reflect: bad state file, resetting")
            return {"last_run_at": None, "last_proposal_id": 0}

    def _write_state_atomic(self, state: dict) -> None:
        path = Path(self._config.get(
            "state_json", "data/strategy/oil_botpattern_reflect_state.json"
        ))
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(state, indent=2, sort_keys=True))
        os.replace(tmp, path)

    # ------------------------------------------------------------------
    # Input loaders
    # ------------------------------------------------------------------

    def _load_closed_trades(self) -> list[dict]:
        path = Path(self._config.get(
            "main_journal_jsonl", "data/research/journal.jsonl"
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
                        row = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if row.get("strategy_id") != "oil_botpattern":
                        continue
                    if row.get("status") != "closed":
                        continue
                    out.append(row)
        except OSError as e:
            log.warning("oil_botpattern_reflect: failed to read %s: %s", path, e)
            return []
        return out

    def _load_decisions(self) -> list[dict]:
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
            log.warning("oil_botpattern_reflect: failed to read %s: %s", path, e)
            return []
        return out

    # ------------------------------------------------------------------
    # Proposals append
    # ------------------------------------------------------------------

    def _append_proposals(self, proposals: list) -> None:
        path = Path(self._config.get(
            "proposals_jsonl", "data/strategy/oil_botpattern_proposals.jsonl"
        ))
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a") as f:
            for p in proposals:
                f.write(json.dumps(proposal_to_dict(p)) + "\n")


# ---------------------------------------------------------------------------
# Helpers reused by the /selftuneapprove Telegram handler.
# ---------------------------------------------------------------------------

def load_proposals(path: str) -> list[dict]:
    """Load all proposals from a JSONL file. Returns [] if file missing."""
    p = Path(path)
    if not p.exists():
        return []
    out: list[dict] = []
    with p.open("r") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return out


def write_proposals_atomic(path: str, proposals: list[dict]) -> None:
    """Atomic rewrite of the proposals JSONL."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    with tmp.open("w") as f:
        for row in proposals:
            f.write(json.dumps(row) + "\n")
    os.replace(tmp, p)


def find_proposal(proposals: list[dict], proposal_id: int) -> dict | None:
    for row in proposals:
        try:
            if int(row.get("id", -1)) == proposal_id:
                return row
        except (TypeError, ValueError):
            continue
    return None
