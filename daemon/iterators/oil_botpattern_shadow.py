"""OilBotPatternShadowIterator — sub-system 6 layer L4 counterfactual eval.

Spec: docs/plans/OIL_BOT_PATTERN_06_SELF_TUNE_HARNESS.md §L4

Scans data/strategy/oil_botpattern_proposals.jsonl for L2 proposals
with status="approved" and no `shadow_eval` field yet. For each one,
runs the counterfactual replay in modules.oil_botpattern_shadow against
the recent decision + closed-trade window, writes a ShadowEval record
to oil_botpattern_shadow_evals.jsonl, and attaches a `shadow_eval`
summary to the proposal record via atomic rewrite.

Kill switch: data/config/oil_botpattern_shadow.json → enabled: false.
Ships enabled=false. Never modifies any config file.

Registered in REBALANCE + OPPORTUNISTIC tiers. Not in WATCH — no
value when no trades are closing.
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
from trading.oil.shadow import (
    ShadowEval,
    evaluate_proposal,
    shadow_eval_to_dict,
)

log = logging.getLogger("daemon.oil_botpattern_shadow")

DEFAULT_CONFIG_PATH = "data/config/oil_botpattern_shadow.json"


class OilBotPatternShadowIterator:
    name = "oil_botpattern_shadow"

    def __init__(self, config_path: str = DEFAULT_CONFIG_PATH):
        self._config_path = Path(config_path)
        self._config: dict = {}
        self._last_poll_mono: float = 0.0

    def on_start(self, ctx: TickContext) -> None:
        self._reload_config()
        if not self._config.get("enabled", False):
            log.info("OilBotPatternShadowIterator disabled — no-op")
            return
        log.info(
            "OilBotPatternShadowIterator started — window=%dd min_sample=%d",
            int(self._config.get("window_days", 30)),
            int(self._config.get("min_sample", 10)),
        )

    def on_stop(self) -> None:
        pass

    def tick(self, ctx: TickContext) -> None:
        self._reload_config()
        if not self._config.get("enabled", False):
            return

        interval = int(self._config.get("tick_interval_s", 3600))
        now_mono = time.monotonic()
        if self._last_poll_mono != 0.0 and (now_mono - self._last_poll_mono) < interval:
            return
        self._last_poll_mono = now_mono

        now = datetime.now(tz=timezone.utc)

        proposals = self._load_proposals()
        if not proposals:
            return

        # Find approved proposals that have NOT been evaluated yet
        pending_eval = [
            p for p in proposals
            if p.get("status") == "approved" and not p.get("shadow_eval")
        ]
        if not pending_eval:
            return

        trades = self._load_closed_trades()
        decisions = self._load_decisions()

        window_days = int(self._config.get("window_days", 30))
        min_sample = int(self._config.get("min_sample", 10))

        new_evals: list[ShadowEval] = []
        dirty = False
        for p in pending_eval:
            try:
                result = evaluate_proposal(
                    p, trades, decisions,
                    now=now, window_days=window_days, min_sample=min_sample,
                )
            except Exception as e:  # noqa: BLE001
                log.warning(
                    "oil_botpattern_shadow: eval failed for #%s: %s",
                    p.get("id"), e,
                )
                continue
            if result is None:
                # Not auto-evaluable — mark so we don't retry every tick
                p["shadow_eval"] = {
                    "status": "not_applicable",
                    "evaluated_at": now.isoformat(),
                    "reason": "proposal is not an auto-evaluable config_change",
                }
                dirty = True
                continue

            new_evals.append(result)
            p["shadow_eval"] = {
                "status": "evaluated",
                "evaluated_at": result.evaluated_at,
                "sample_sufficient": result.sample_sufficient,
                "would_have_diverged": result.would_have_diverged,
                "divergence_rate": result.divergence_rate,
                "counterfactual_pnl_estimate_usd": result.counterfactual_pnl_estimate_usd,
                "notes": result.notes,
            }
            dirty = True

        if not dirty:
            return

        try:
            self._write_proposals_atomic(proposals)
        except OSError as e:
            log.warning("oil_botpattern_shadow: failed to rewrite proposals: %s", e)
            return

        if new_evals:
            try:
                self._append_evals(new_evals)
            except OSError as e:
                log.warning("oil_botpattern_shadow: failed to append evals: %s", e)

            ids = ", ".join(f"#{e.proposal_id}" for e in new_evals)
            log.info(
                "oil_botpattern_shadow: evaluated %d proposal(s): %s",
                len(new_evals), ids,
            )
            ctx.alerts.append(Alert(
                severity="info", source=self.name,
                message=(
                    f"oil_botpattern_shadow: counterfactual eval completed "
                    f"for {len(new_evals)} proposal(s) ({ids}). "
                    f"Run /shadoweval to review."
                ),
                data={
                    "count": len(new_evals),
                    "ids": [e.proposal_id for e in new_evals],
                },
            ))

    # ------------------------------------------------------------------
    # Config
    # ------------------------------------------------------------------

    def _reload_config(self) -> None:
        try:
            self._config = json.loads(self._config_path.read_text())
        except (FileNotFoundError, json.JSONDecodeError) as e:
            log.warning("oil_botpattern_shadow config unavailable (%s)", e)
            self._config = {"enabled": False}

    # ------------------------------------------------------------------
    # Input loaders
    # ------------------------------------------------------------------

    def _load_proposals(self) -> list[dict]:
        path = Path(self._config.get(
            "proposals_jsonl", "data/strategy/oil_botpattern_proposals.jsonl"
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
        except OSError:
            return []
        return out

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
        except OSError:
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
        except OSError:
            return []
        return out

    # ------------------------------------------------------------------
    # Output writers
    # ------------------------------------------------------------------

    def _write_proposals_atomic(self, proposals: list[dict]) -> None:
        path = Path(self._config.get(
            "proposals_jsonl", "data/strategy/oil_botpattern_proposals.jsonl"
        ))
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        with tmp.open("w") as f:
            for row in proposals:
                f.write(json.dumps(row) + "\n")
        os.replace(tmp, path)

    def _append_evals(self, evals: list[ShadowEval]) -> None:
        path = Path(self._config.get(
            "shadow_evals_jsonl", "data/strategy/oil_botpattern_shadow_evals.jsonl"
        ))
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a") as f:
            for e in evals:
                f.write(json.dumps(shadow_eval_to_dict(e)) + "\n")


# ---------------------------------------------------------------------------
# Helpers for the /shadoweval Telegram handler
# ---------------------------------------------------------------------------

def load_shadow_evals(path: str) -> list[dict]:
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


def find_shadow_eval(evals: list[dict], proposal_id: int) -> dict | None:
    # Return the most recent eval for this proposal_id
    matches = [e for e in evals if int(e.get("proposal_id", -1)) == proposal_id]
    if not matches:
        return None
    return matches[-1]
