"""OilBotPatternPatternLibIterator — sub-system 6 layer L3 pattern library.

Spec: docs/plans/OIL_BOT_PATTERN_06_SELF_TUNE_HARNESS.md

Watches data/research/bot_patterns.jsonl, detects novel signatures
(classification, direction, confidence_band, signals), tallies their
occurrences in a rolling window, and writes PatternCandidate records
to data/research/bot_pattern_candidates.jsonl once a signature crosses
min_occurrences.

Kill switch: data/config/oil_botpattern_patternlib.json → enabled: false.
Ships with enabled=false.

Registered in ALL THREE tiers (unlike L1/L2). Reason: this iterator is
read-only against bot_patterns.jsonl and write-only to its own files.
It doesn't mutate any config, doesn't affect sub-system 5 behavior, and
doesn't trade. Safe to run in WATCH where catalog growth still has
value even without live trading.

Does NOT modify sub-system 4's classifier behavior — L3 is purely
observational. A future wedge can teach sub-system 4 to gate on the
promoted catalog.
"""
from __future__ import annotations

import json
import logging
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from cli.daemon.context import Alert, TickContext
from modules.oil_botpattern_patternlib import (
    candidate_to_dict,
    detect_novel_signatures,
    extract_candidate_keys,
    promote_to_catalog,
)

log = logging.getLogger("daemon.oil_botpattern_patternlib")

DEFAULT_CONFIG_PATH = "data/config/oil_botpattern_patternlib.json"


class OilBotPatternPatternLibIterator:
    name = "oil_botpattern_patternlib"

    def __init__(self, config_path: str = DEFAULT_CONFIG_PATH):
        self._config_path = Path(config_path)
        self._config: dict = {}
        self._last_poll_mono: float = 0.0

    def on_start(self, ctx: TickContext) -> None:
        self._reload_config()
        if not self._config.get("enabled", False):
            log.info("OilBotPatternPatternLibIterator disabled — no-op")
            return
        log.info(
            "OilBotPatternPatternLibIterator started — min_occ=%d precision=%.2f window=%dd",
            int(self._config.get("min_occurrences", 3)),
            float(self._config.get("confidence_band_precision", 0.1)),
            int(self._config.get("window_days", 30)),
        )

    def on_stop(self) -> None:
        pass

    def tick(self, ctx: TickContext) -> None:
        self._reload_config()
        if not self._config.get("enabled", False):
            return

        interval = int(self._config.get("tick_interval_s", 600))
        now_mono = time.monotonic()
        if self._last_poll_mono != 0.0 and (now_mono - self._last_poll_mono) < interval:
            return
        self._last_poll_mono = now_mono

        now = datetime.now(tz=timezone.utc)

        rows = self._load_bot_patterns()
        if not rows:
            return

        catalog = self._load_catalog()
        existing_candidates = self._load_candidates()
        state = self._load_state()

        existing_keys = extract_candidate_keys(existing_candidates)
        next_id = int(state.get("last_candidate_id", 0)) + 1

        new_candidates = detect_novel_signatures(
            rows=rows,
            catalog=catalog,
            min_occurrences=int(self._config.get("min_occurrences", 3)),
            precision=float(self._config.get("confidence_band_precision", 0.1)),
            now=now,
            window_days=int(self._config.get("window_days", 30)),
            next_id=next_id,
            existing_candidate_keys=existing_keys,
        )

        if not new_candidates:
            return

        try:
            self._append_candidates(new_candidates)
        except OSError as e:
            log.warning("oil_botpattern_patternlib: failed to append candidates: %s", e)
            return

        state["last_candidate_id"] = max(c.id for c in new_candidates)
        state["last_run_at"] = now.isoformat()
        try:
            self._write_state_atomic(state)
        except OSError as e:
            log.warning("oil_botpattern_patternlib: failed to write state: %s", e)

        ids_str = ", ".join(f"#{c.id}" for c in new_candidates)
        log.info(
            "oil_botpattern_patternlib: %d novel signature(s) detected (%s)",
            len(new_candidates), ids_str,
        )
        ctx.alerts.append(Alert(
            severity="info", source=self.name,
            message=(
                f"oil_botpattern_patternlib: {len(new_candidates)} new "
                f"pattern candidate(s) pending review ({ids_str}). "
                f"Run /patterncatalog to review."
            ),
            data={
                "count": len(new_candidates),
                "ids": [c.id for c in new_candidates],
            },
        ))

    # ------------------------------------------------------------------
    # Config + state
    # ------------------------------------------------------------------

    def _reload_config(self) -> None:
        try:
            self._config = json.loads(self._config_path.read_text())
        except (FileNotFoundError, json.JSONDecodeError) as e:
            log.warning("oil_botpattern_patternlib config unavailable (%s)", e)
            self._config = {"enabled": False}

    def _load_state(self) -> dict:
        path = Path(self._config.get(
            "state_json", "data/strategy/oil_botpattern_patternlib_state.json"
        ))
        if not path.exists():
            return {"last_candidate_id": 0, "last_run_at": None}
        try:
            return json.loads(path.read_text())
        except (OSError, json.JSONDecodeError):
            log.warning("oil_botpattern_patternlib: bad state, resetting")
            return {"last_candidate_id": 0, "last_run_at": None}

    def _write_state_atomic(self, state: dict) -> None:
        path = Path(self._config.get(
            "state_json", "data/strategy/oil_botpattern_patternlib_state.json"
        ))
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(state, indent=2, sort_keys=True))
        os.replace(tmp, path)

    # ------------------------------------------------------------------
    # Input loaders
    # ------------------------------------------------------------------

    def _load_bot_patterns(self) -> list[dict]:
        path = Path(self._config.get(
            "bot_patterns_jsonl", "data/research/bot_patterns.jsonl"
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
            log.warning("oil_botpattern_patternlib: failed to read %s: %s", path, e)
            return []
        return out

    def _load_catalog(self) -> dict:
        path = Path(self._config.get(
            "catalog_json", "data/research/bot_pattern_catalog.json"
        ))
        if not path.exists():
            return {}
        try:
            data = json.loads(path.read_text())
            return data if isinstance(data, dict) else {}
        except (OSError, json.JSONDecodeError):
            return {}

    def _load_candidates(self) -> list[dict]:
        path = Path(self._config.get(
            "candidates_jsonl", "data/research/bot_pattern_candidates.jsonl"
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
    # Candidate append
    # ------------------------------------------------------------------

    def _append_candidates(self, candidates: list) -> None:
        path = Path(self._config.get(
            "candidates_jsonl", "data/research/bot_pattern_candidates.jsonl"
        ))
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a") as f:
            for c in candidates:
                f.write(json.dumps(candidate_to_dict(c)) + "\n")


# ---------------------------------------------------------------------------
# Helpers reused by the /patternpromote + /patternreject Telegram handlers.
# ---------------------------------------------------------------------------

def load_candidates(path: str) -> list[dict]:
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


def write_candidates_atomic(path: str, candidates: list[dict]) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    with tmp.open("w") as f:
        for row in candidates:
            f.write(json.dumps(row) + "\n")
    os.replace(tmp, p)


def find_candidate(candidates: list[dict], candidate_id: int) -> dict | None:
    for row in candidates:
        try:
            if int(row.get("id", -1)) == candidate_id:
                return row
        except (TypeError, ValueError):
            continue
    return None


def load_catalog(path: str) -> dict:
    p = Path(path)
    if not p.exists():
        return {}
    try:
        data = json.loads(p.read_text())
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def write_catalog_atomic(path: str, catalog: dict) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(json.dumps(catalog, indent=2, sort_keys=True))
    os.replace(tmp, p)


def apply_promote(
    catalog_path: str,
    candidates_path: str,
    candidate_id: int,
    now_iso: str,
) -> tuple[bool, str]:
    """Promote a pending candidate to the live catalog atomically.

    Returns (ok, message). Rewrites both files on success. Never raises
    — errors come back as ok=False.
    """
    candidates = load_candidates(candidates_path)
    target = find_candidate(candidates, candidate_id)
    if target is None:
        return (False, f"candidate #{candidate_id} not found")
    if target.get("status") != "pending":
        return (False, f"candidate #{candidate_id} is {target.get('status')}, not pending")

    catalog = load_catalog(catalog_path)
    new_catalog = promote_to_catalog(catalog, target, now_iso)
    try:
        write_catalog_atomic(catalog_path, new_catalog)
    except OSError as e:
        return (False, f"catalog write failed: {e}")

    target["status"] = "promoted"
    target["reviewed_at"] = now_iso
    try:
        write_candidates_atomic(candidates_path, candidates)
    except OSError as e:
        return (False, f"catalog updated but candidate file write failed: {e}")

    return (True, f"promoted candidate #{candidate_id} to live catalog")


def apply_reject(
    candidates_path: str,
    candidate_id: int,
    now_iso: str,
) -> tuple[bool, str]:
    """Mark a pending candidate rejected. Catalog is NOT touched."""
    candidates = load_candidates(candidates_path)
    target = find_candidate(candidates, candidate_id)
    if target is None:
        return (False, f"candidate #{candidate_id} not found")
    if target.get("status") != "pending":
        return (False, f"candidate #{candidate_id} is {target.get('status')}, not pending")

    target["status"] = "rejected"
    target["reviewed_at"] = now_iso
    try:
        write_candidates_atomic(candidates_path, candidates)
    except OSError as e:
        return (False, f"candidate file write failed: {e}")

    return (True, f"rejected candidate #{candidate_id}")
