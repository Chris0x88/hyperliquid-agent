"""LessonAuthorIterator — watches journal.jsonl for closed positions and
writes verbatim lesson candidate files for later authoring.

This is wedge 5 of the trade lesson layer. The iterator is intentionally
"dumb" — it does no AI calls, no LLM, no model interaction whatsoever.
It only assembles the verbatim source context (closed JournalEntry +
optional thesis snapshot + optional learnings.md slice) and writes the
result to disk as a candidate JSON file.

The actual "agent authors the post-mortem and persists to the lessons
table" step is a future wedge — it can live in the dream cycle, in a
Telegram-side periodic task, or in a manual /lesson author <id> command.
Decoupling the watcher from the model call mirrors the existing
autoresearch.py pattern (the daemon never calls the model directly;
it writes structured outputs that the agent reads on its own loop).

Cursor tracking: a tiny state file at
``data/daemon/lesson_author_state.json`` stores the last byte offset
read from journal.jsonl plus a set of processed entry_ids. On every
tick the iterator seeks to the last offset, parses new lines, filters
to closed-position records, and writes one candidate file per close.
Dedup is done two ways:
  1. In-memory `_processed_ids` set to skip rows already seen this run.
  2. Filesystem check on the candidate filename (deterministic from
     entry_id) to skip rows seen in a previous daemon run.

Kill switch: ``data/config/lesson_author.json`` → ``{"enabled": false}``.

Refuse-to-write-garbage rule (Bug A pattern from 2026-04-08): if the
journal row is missing required fields (entry_id, instrument,
direction, exit_price, pnl, close_ts) or the values are obviously
broken (entry_price/exit_price = 0, |roe_pct| > 1000), the row is
logged and skipped — no candidate file is written.
"""
from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any, Optional

from daemon.context import TickContext

log = logging.getLogger("daemon.lesson_author")

DEFAULT_CONFIG_PATH = "data/config/lesson_author.json"
DEFAULT_JOURNAL_PATH = "data/research/journal.jsonl"
DEFAULT_STATE_PATH = "data/daemon/lesson_author_state.json"
DEFAULT_CANDIDATE_DIR = "data/daemon/lesson_candidates"
DEFAULT_THESIS_BACKUP_DIR = "data/thesis_backup"
DEFAULT_LEARNINGS_PATH = "data/research/learnings.md"
DEFAULT_CATALYSTS_PATH = "data/news/catalysts.jsonl"


class LessonAuthorIterator:
    name = "lesson_author"

    def __init__(
        self,
        config_path: str = DEFAULT_CONFIG_PATH,
        journal_path: str = DEFAULT_JOURNAL_PATH,
        state_path: str = DEFAULT_STATE_PATH,
        candidate_dir: str = DEFAULT_CANDIDATE_DIR,
        thesis_backup_dir: str = DEFAULT_THESIS_BACKUP_DIR,
        learnings_path: str = DEFAULT_LEARNINGS_PATH,
        catalysts_path: str = DEFAULT_CATALYSTS_PATH,
    ):
        self._config_path = Path(config_path)
        self._journal_path = Path(journal_path)
        self._state_path = Path(state_path)
        self._candidate_dir = Path(candidate_dir)
        self._thesis_backup_dir = Path(thesis_backup_dir)
        self._learnings_path = Path(learnings_path)
        self._catalysts_path = Path(catalysts_path)
        self._enabled: bool = True
        self._last_offset: int = 0
        self._processed_ids: set[str] = set()

    # ── Lifecycle ────────────────────────────────────────────

    def on_start(self, ctx: TickContext) -> None:
        self._reload_config()
        if not self._enabled:
            log.info("LessonAuthorIterator disabled via config — no-op")
            return
        self._candidate_dir.mkdir(parents=True, exist_ok=True)
        self._load_state()
        log.info(
            "LessonAuthorIterator started (offset=%d, processed=%d)",
            self._last_offset,
            len(self._processed_ids),
        )

    def on_stop(self) -> None:
        if self._enabled:
            self._save_state()

    def tick(self, ctx: TickContext) -> None:
        self._reload_config()
        if not self._enabled:
            return
        if not self._journal_path.exists():
            return
        try:
            new_lines = self._read_new_lines()
        except OSError as e:
            log.warning("LessonAuthor: failed to read journal: %s", e)
            return

        if not new_lines:
            return

        wrote = 0
        skipped = 0
        for raw in new_lines:
            try:
                entry = json.loads(raw)
            except json.JSONDecodeError:
                skipped += 1
                continue

            if not _is_closed_position(entry):
                continue  # tick snapshot or non-close row, ignore

            entry_id = str(entry.get("entry_id", "") or "")
            if not entry_id:
                log.warning("LessonAuthor: closed entry missing entry_id, skipping")
                skipped += 1
                continue

            if entry_id in self._processed_ids:
                continue

            if not _is_valid_close(entry):
                log.warning(
                    "LessonAuthor: garbage close (entry_id=%s, entry=$%s, exit=$%s, "
                    "roe=%s) — skipping per Bug A refuse-to-write rule",
                    entry_id,
                    entry.get("entry_price"),
                    entry.get("exit_price"),
                    entry.get("roe_pct"),
                )
                self._processed_ids.add(entry_id)
                skipped += 1
                continue

            candidate_path = self._candidate_dir / _safe_filename(entry_id)
            if candidate_path.exists():
                # Already written in a previous daemon run
                self._processed_ids.add(entry_id)
                continue

            request = self._assemble_request(entry)
            try:
                _write_candidate_atomic(candidate_path, request)
            except OSError as e:
                log.warning("LessonAuthor: failed to write candidate %s: %s", entry_id, e)
                continue

            self._processed_ids.add(entry_id)
            wrote += 1

        if wrote or skipped:
            self._save_state()
            log.info(
                "LessonAuthor: tick complete (wrote=%d, skipped=%d, total_processed=%d)",
                wrote,
                skipped,
                len(self._processed_ids),
            )

    # ── Config + state ───────────────────────────────────────

    def _reload_config(self) -> None:
        if not self._config_path.exists():
            self._enabled = True  # default ON
            return
        try:
            with self._config_path.open("r") as f:
                cfg = json.load(f)
            self._enabled = bool(cfg.get("enabled", True))
        except (OSError, json.JSONDecodeError) as e:
            log.warning("LessonAuthor: bad config %s: %s — defaulting to enabled", self._config_path, e)
            self._enabled = True

    def _load_state(self) -> None:
        if not self._state_path.exists():
            self._last_offset = 0
            self._processed_ids = set()
            return
        try:
            with self._state_path.open("r") as f:
                state = json.load(f)
            self._last_offset = int(state.get("last_offset", 0))
            self._processed_ids = set(state.get("processed_ids", []))
        except (OSError, json.JSONDecodeError, ValueError) as e:
            log.warning("LessonAuthor: bad state %s: %s — resetting", self._state_path, e)
            self._last_offset = 0
            self._processed_ids = set()

    def _save_state(self) -> None:
        try:
            self._state_path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self._state_path.with_suffix(".tmp")
            with tmp.open("w") as f:
                json.dump(
                    {
                        "last_offset": self._last_offset,
                        # Cap at last 1000 to bound state file growth
                        "processed_ids": sorted(self._processed_ids)[-1000:],
                    },
                    f,
                )
            tmp.replace(self._state_path)
        except OSError as e:
            log.warning("LessonAuthor: failed to save state: %s", e)

    # ── Journal reading ──────────────────────────────────────

    def _read_new_lines(self) -> list[str]:
        """Read lines from journal.jsonl since the last byte offset.

        Handles file truncation (offset > current size) by resetting to 0.
        Updates self._last_offset on success.
        """
        size = self._journal_path.stat().st_size
        if self._last_offset > size:
            log.info(
                "LessonAuthor: journal truncated (offset=%d > size=%d) — resetting",
                self._last_offset,
                size,
            )
            self._last_offset = 0

        with self._journal_path.open("r") as f:
            f.seek(self._last_offset)
            chunk = f.read()
            self._last_offset = f.tell()

        if not chunk:
            return []
        return [line for line in chunk.splitlines() if line.strip()]

    # ── Context assembly ─────────────────────────────────────

    def _assemble_request(self, entry: dict) -> dict:
        """Build the verbatim LessonAuthorRequest dict for one closed entry.

        Mirrors modules.lesson_engine.LessonAuthorRequest exactly so the
        candidate file can be loaded into a Lesson directly when the
        authoring step ships.
        """
        market = str(entry.get("instrument") or "")
        direction = str(entry.get("direction") or "")
        thesis_snapshot, thesis_snapshot_path = self._load_thesis_snapshot(market, direction)
        learnings_slice = self._read_learnings_tail(max_chars=2000)
        news_context = self._read_catalysts_window(
            market=market,
            entry_ts_ms=entry.get("entry_ts"),
            close_ts_ms=entry.get("close_ts"),
        )

        return {
            "schema_version": 1,
            "kind": "lesson_candidate",
            "created_at": _now_iso(),
            "journal_entry": entry,
            "thesis_snapshot": thesis_snapshot,
            "thesis_snapshot_path": thesis_snapshot_path,
            "learnings_md_slice": learnings_slice,
            "news_context_at_open": news_context,
            "autoresearch_eval_window": "",  # placeholder — future wedge
            # Pre-extracted fields the consumer will need to call log_lesson:
            "market": market,
            "direction": direction,
            "signal_source": str(entry.get("entry_source") or "manual"),
            "pnl_usd": float(entry.get("pnl") or 0.0),
            "roe_pct": float(entry.get("roe_pct") or 0.0),
            "holding_ms": int(entry.get("holding_ms") or 0),
            "trade_closed_at": _ms_to_iso(entry.get("close_ts")),
            "journal_entry_id": str(entry.get("entry_id") or ""),
        }

    def _load_thesis_snapshot(
        self, market: str, direction: str
    ) -> tuple[Optional[dict], Optional[str]]:
        """Best-effort load of the thesis state at the time the position was
        opened. Uses H6 dual-write at data/thesis_backup/ if available, falls
        back to None when no snapshot exists. Never raises — thesis snapshots
        are nice-to-have, not required for a candidate."""
        if not market:
            return None, None
        if not self._thesis_backup_dir.exists():
            return None, None

        # H6 backups use the same filename as the live thesis file. We pick
        # the most recently modified backup that matches the market.
        # Naming convention: {market}_state.json or {market_safe}_state.json.
        candidates = sorted(
            self._thesis_backup_dir.glob("*_state.json"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        for path in candidates:
            try:
                with path.open("r") as f:
                    data = json.load(f)
            except (OSError, json.JSONDecodeError):
                continue
            if data.get("market") == market and data.get("direction") in (direction, "long", "short"):
                return data, str(path)
        return None, None

    def _read_catalysts_window(
        self,
        market: str,
        entry_ts_ms: Any,
        close_ts_ms: Any,
        max_catalysts: int = 20,
    ) -> str:
        """Return a markdown summary of catalysts from sub-system 1's
        ``data/news/catalysts.jsonl`` whose ``event_date`` falls between
        ``entry_ts`` and ``close_ts`` AND whose ``instruments`` list contains
        the trade's market (or a stripped form of it).

        Returns ``""`` on missing file, missing/invalid timestamps, or no
        matching catalysts. Never raises — news enrichment is best-effort
        and must not break the candidate write."""
        if not self._catalysts_path.exists():
            return ""
        try:
            entry_ms = int(entry_ts_ms) if entry_ts_ms is not None else None
            close_ms = int(close_ts_ms) if close_ts_ms is not None else None
        except (TypeError, ValueError):
            return ""
        if entry_ms is None or close_ms is None or close_ms < entry_ms:
            return ""

        # Build the set of acceptable instrument strings — handle the xyz:
        # prefix mismatch (data store has 'xyz:BRENTOIL', CL/BRENTOIL etc).
        market_set: set[str] = set()
        if market:
            market_set.add(market)
            if market.startswith("xyz:"):
                market_set.add(market[len("xyz:"):])
            else:
                market_set.add(f"xyz:{market}")

        from datetime import datetime, timezone

        try:
            with self._catalysts_path.open("r") as f:
                lines = f.readlines()
        except OSError:
            return ""

        hits: list[dict] = []
        for line in lines:
            line = line.strip()
            if not line:
                continue
            try:
                cat = json.loads(line)
            except json.JSONDecodeError:
                continue

            instruments = cat.get("instruments") or []
            if not isinstance(instruments, list):
                continue
            if market_set and not any(i in market_set for i in instruments):
                continue

            event_date = cat.get("event_date")
            if not event_date:
                continue
            try:
                ed = datetime.fromisoformat(event_date)
                if ed.tzinfo is None:
                    ed = ed.replace(tzinfo=timezone.utc)
                ed_ms = int(ed.timestamp() * 1000)
            except (ValueError, TypeError):
                continue

            if entry_ms <= ed_ms <= close_ms:
                hits.append(cat)

        if not hits:
            return ""

        # Sort by severity DESC then event_date ASC, cap at max_catalysts
        hits.sort(key=lambda c: (-int(c.get("severity", 0)), c.get("event_date", "")))
        hits = hits[:max_catalysts]

        lines_out: list[str] = [
            f"Catalysts touching {market} between trade open and close "
            f"({len(hits)} matching):",
        ]
        for c in hits:
            sev = int(c.get("severity", 0))
            cat = c.get("category", "?")
            ed = (c.get("event_date") or "")[:16].replace("T", " ")
            direction = c.get("expected_direction") or "?"
            rationale = c.get("rationale", "")
            lines_out.append(f"- sev={sev} {cat} @ {ed}Z dir={direction} — {rationale}")
        return "\n".join(lines_out)

    def _read_learnings_tail(self, max_chars: int = 2000) -> str:
        """Return the tail of learnings.md, capped at max_chars. Empty string
        on missing file or read error."""
        if not self._learnings_path.exists():
            return ""
        try:
            with self._learnings_path.open("r") as f:
                content = f.read()
        except OSError:
            return ""
        if len(content) <= max_chars:
            return content
        return "... [truncated]\n" + content[-max_chars:]


# ── Module-level helpers ────────────────────────────────────


def _is_closed_position(entry: dict) -> bool:
    """A closed-position row has an entry_id, an exit_price, a close_ts, and
    a pnl. Tick snapshots have none of these. Return True only if all three
    structural markers are present."""
    return (
        "entry_id" in entry
        and "exit_price" in entry
        and "close_ts" in entry
        and "pnl" in entry
    )


def _is_valid_close(entry: dict) -> bool:
    """Refuse to write garbage. Filter out the 2026-04-08 Bug A pattern:
    exit_price=0 producing fake +/-100% PnL on a real position. Also catches
    other obvious corruption (negative holding time, |roe| > 1000)."""
    try:
        entry_price = float(entry.get("entry_price") or 0)
        exit_price = float(entry.get("exit_price") or 0)
        roe_pct = float(entry.get("roe_pct") or 0)
        holding_ms = int(entry.get("holding_ms") or 0)
    except (TypeError, ValueError):
        return False
    if entry_price <= 0:
        return False
    if exit_price <= 0:
        return False
    if abs(roe_pct) > 1000:
        return False
    if holding_ms < 0:
        return False
    return True


def _safe_filename(entry_id: str) -> str:
    """Make entry_id filesystem-safe (replace : / etc) and add .json suffix.
    The xyz: prefix is the most common slash-unsafe character."""
    safe = entry_id.replace(":", "_").replace("/", "_").replace(" ", "_")
    return f"{safe}.json"


def _write_candidate_atomic(path: Path, candidate: dict) -> None:
    """Write a candidate file atomically via .tmp + rename."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w") as f:
        json.dump(candidate, f, indent=2, sort_keys=True, default=str)
    tmp.replace(path)


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _ms_to_iso(ms: Any) -> str:
    """Convert a millisecond timestamp to ISO 8601 UTC. Returns "" on bad input."""
    try:
        ts = int(ms) / 1000.0
    except (TypeError, ValueError):
        return ""
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(ts))
