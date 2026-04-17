#!/usr/bin/env python3
"""One-shot backfill: seed the lessons table from existing closed-trade history.

USAGE
-----
    cd agent-cli
    .venv/bin/python scripts/backfill_lessons.py [--dry-run] [--force]

    --dry-run   Print what would be done; write nothing.
    --force     Re-write candidate files even if they already exist.
                (Lessons already in the DB are still skipped unless you DELETE
                them manually — the lessons table is append-only.)

WHAT IT DOES
------------
1. Reads data/research/journal.jsonl, normalises via _normalize_journal_row,
   filters to closed-position rows.
2. Reads data/research/entry_critiques.jsonl.
3. Joins each closed trade to its nearest critique by (instrument, entry_ts +/-
   60 s). Join is best-effort; a missing critique is not an error.
4. Checks the lessons table for each trade_id/entry_id and skips any that are
   already present (idempotent by default).
5. Assembles a lesson_candidate dict matching the LessonAuthorRequest schema
   used by daemon/iterators/lesson_author.py.
6. Writes the candidate to data/daemon/lesson_candidates/<entry_id>.json
   (atomic write via .tmp + rename, same as the live iterator).

The lesson_consumer (or a future /lesson author command) picks up candidates
from that directory and calls the LLM + common.memory.log_lesson.

CANDIDATE SCHEMA
----------------
See daemon/iterators/lesson_author.py::LessonAuthorIterator._assemble_request
for the exact shape.  The backfill script replicates that shape exactly so
candidates produced here are indistinguishable from daemon-produced ones.

IDEMPOTENCY
-----------
Idempotency is two-layer:
  1. Lessons table: if journal_entry_id already appears in lessons.journal_entry_id
     the trade is skipped (even with --force).
  2. Candidate files: if the .json file already exists in lesson_candidates/ it
     is skipped (unless --force).

SUMMARY LINE
------------
At the end the script prints:
    N candidates written, N already-in-db skipped, N candidate-exists skipped,
    N malformed/garbage skipped
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
import time
from pathlib import Path
from typing import Any, Optional

# ---------------------------------------------------------------------------
# Path constants — all relative to the agent-cli root (cwd expected).
# ---------------------------------------------------------------------------

ROOT = Path(__file__).resolve().parent.parent  # agent-cli/

JOURNAL_PATH = ROOT / "data" / "research" / "journal.jsonl"
CRITIQUES_PATH = ROOT / "data" / "research" / "entry_critiques.jsonl"
CANDIDATE_DIR = ROOT / "data" / "daemon" / "lesson_candidates"
DB_PATH = ROOT / "data" / "memory" / "memory.db"
LEARNINGS_PATH = ROOT / "data" / "research" / "learnings.md"
THESIS_BACKUP_DIR = ROOT / "data" / "thesis_backup"
CATALYSTS_PATH = ROOT / "data" / "news" / "catalysts.jsonl"

# Maximum timestamp delta (ms) for a critique to be considered "matching" the
# trade's open time.
CRITIQUE_JOIN_WINDOW_MS = 60 * 1000  # 60 seconds


# ---------------------------------------------------------------------------
# Import helpers from the daemon iterator (no duplication).
# ---------------------------------------------------------------------------

def _import_lesson_author_helpers():
    """Import from daemon.iterators.lesson_author with a friendly error."""
    sys.path.insert(0, str(ROOT))
    try:
        from daemon.iterators.lesson_author import (
            _normalize_journal_row,
            _is_closed_position,
            _is_valid_close,
            _safe_filename,
            _write_candidate_atomic,
            _now_iso,
            _ms_to_iso,
        )
        return (
            _normalize_journal_row,
            _is_closed_position,
            _is_valid_close,
            _safe_filename,
            _write_candidate_atomic,
            _now_iso,
            _ms_to_iso,
        )
    except ImportError as exc:
        print(f"ERROR: cannot import from daemon.iterators.lesson_author: {exc}", file=sys.stderr)
        print("Make sure you are running from the agent-cli directory.", file=sys.stderr)
        sys.exit(1)


# ---------------------------------------------------------------------------
# Core logic — pure functions so tests can call them directly.
# ---------------------------------------------------------------------------

def load_journal(path: Path) -> list[dict]:
    """Read journal.jsonl and return all parsed rows (malformed lines skipped)."""
    rows: list[dict] = []
    if not path.exists():
        return rows
    with path.open("r") as f:
        for lineno, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError as exc:
                print(f"  WARN journal line {lineno}: {exc}", file=sys.stderr)
    return rows


def load_critiques(path: Path) -> list[dict]:
    """Read entry_critiques.jsonl and return all parsed rows."""
    rows: list[dict] = []
    if not path.exists():
        return rows
    with path.open("r") as f:
        for lineno, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError as exc:
                print(f"  WARN critiques line {lineno}: {exc}", file=sys.stderr)
    return rows


def _instrument_key(instrument: str) -> str:
    """Normalise instrument for comparison: strip xyz: prefix, uppercase."""
    if instrument is None:
        return ""
    s = str(instrument)
    if s.startswith("xyz:"):
        s = s[len("xyz:"):]
    return s.upper()


def build_critique_index(critiques: list[dict]) -> dict[str, list[dict]]:
    """Index critiques by normalised instrument key for fast lookup."""
    index: dict[str, list[dict]] = {}
    for c in critiques:
        key = _instrument_key(c.get("instrument", ""))
        if key:
            index.setdefault(key, []).append(c)
    return index


def find_matching_critique(
    entry: dict,
    critique_index: dict[str, list[dict]],
    window_ms: int = CRITIQUE_JOIN_WINDOW_MS,
) -> Optional[dict]:
    """Return the critique whose entry_ts is closest to the trade's entry_ts,
    within window_ms.  Returns None if no match exists."""
    instrument = entry.get("instrument", "")
    key = _instrument_key(instrument)
    candidates = critique_index.get(key, [])
    if not candidates:
        return None

    try:
        trade_entry_ts = int(entry.get("entry_ts") or 0)
    except (TypeError, ValueError):
        return None
    if trade_entry_ts == 0:
        return None

    best: Optional[dict] = None
    best_delta = window_ms + 1  # outside window initially

    for c in candidates:
        try:
            c_ts = int(c.get("entry_ts_ms") or 0)
        except (TypeError, ValueError):
            continue
        if c_ts == 0:
            continue
        delta = abs(c_ts - trade_entry_ts)
        if delta < best_delta:
            best_delta = delta
            best = c

    return best if best_delta <= window_ms else None


def get_db_entry_ids(db_path: Path) -> set[str]:
    """Return the set of journal_entry_id values already in the lessons table."""
    if not db_path.exists():
        return set()
    try:
        con = sqlite3.connect(str(db_path))
        rows = con.execute(
            "SELECT journal_entry_id FROM lessons WHERE journal_entry_id IS NOT NULL"
        ).fetchall()
        con.close()
        return {str(r[0]) for r in rows}
    except sqlite3.Error:
        return set()


def read_learnings_tail(path: Path, max_chars: int = 2000) -> str:
    """Return the tail of learnings.md, capped at max_chars."""
    if not path.exists():
        return ""
    try:
        content = path.read_text()
    except OSError:
        return ""
    if len(content) <= max_chars:
        return content
    return "... [truncated]\n" + content[-max_chars:]


def load_thesis_snapshot(
    market: str, thesis_backup_dir: Path
) -> tuple[Optional[dict], Optional[str]]:
    """Best-effort load of the most-recent thesis backup for this market."""
    if not market or not thesis_backup_dir.exists():
        return None, None
    candidates = sorted(
        thesis_backup_dir.glob("*_state.json"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    for path in candidates:
        try:
            data = json.loads(path.read_text())
        except (OSError, json.JSONDecodeError):
            continue
        if data.get("market") == market:
            return data, str(path)
    return None, None


def assemble_candidate(
    entry: dict,
    critique: Optional[dict],
    learnings_slice: str,
    thesis_snapshot: Optional[dict],
    thesis_snapshot_path: Optional[str],
    now_iso_fn,
    ms_to_iso_fn,
) -> dict:
    """Build a lesson_candidate dict matching LessonAuthorIterator._assemble_request.

    Includes the matched critique (if any) in the journal_entry under the key
    ``entry_critique`` so the authoring step has the grading context.
    """
    market = str(entry.get("instrument") or "")
    direction = str(entry.get("direction") or "").lower()

    # Normalise direction to canonical values (LONG -> long, etc.)
    if direction not in ("long", "short", "flat"):
        direction = direction.lower()

    # Merge critique into the journal entry snapshot for the authoring context.
    journal_entry_with_critique = dict(entry)
    if critique is not None:
        journal_entry_with_critique["entry_critique"] = critique

    return {
        "schema_version": 1,
        "kind": "lesson_candidate",
        "created_at": now_iso_fn(),
        "backfill": True,  # flag so the consumer knows this came from backfill
        "journal_entry": journal_entry_with_critique,
        "thesis_snapshot": thesis_snapshot,
        "thesis_snapshot_path": thesis_snapshot_path,
        "learnings_md_slice": learnings_slice,
        "news_context_at_open": "",  # not available in backfill
        "autoresearch_eval_window": "",  # placeholder
        # Pre-extracted fields the consumer will need to call log_lesson:
        "market": market,
        "direction": direction,
        "signal_source": str(entry.get("entry_source") or "manual"),
        "pnl_usd": float(entry.get("pnl") or 0.0),
        "roe_pct": float(entry.get("roe_pct") or 0.0),
        "holding_ms": int(entry.get("holding_ms") or 0),
        "trade_closed_at": ms_to_iso_fn(entry.get("close_ts")),
        "journal_entry_id": str(entry.get("entry_id") or ""),
        "conviction_at_open": entry.get("conviction_at_close"),  # best proxy available
    }


def run_backfill(
    journal_path: Path = JOURNAL_PATH,
    critiques_path: Path = CRITIQUES_PATH,
    candidate_dir: Path = CANDIDATE_DIR,
    db_path: Path = DB_PATH,
    learnings_path: Path = LEARNINGS_PATH,
    thesis_backup_dir: Path = THESIS_BACKUP_DIR,
    dry_run: bool = False,
    force: bool = False,
    verbose: bool = True,
) -> dict[str, int]:
    """Main backfill logic. Returns a summary dict with counts.

    Returns:
        {
            "written": int,        # candidate files written
            "in_db_skipped": int,  # trades already in lessons table
            "exists_skipped": int, # candidate file exists (and --force not set)
            "garbage_skipped": int,# rows that failed validation
            "malformed_skipped": int, # rows that couldn't be parsed
        }
    """
    (
        _normalize_journal_row,
        _is_closed_position,
        _is_valid_close,
        _safe_filename,
        _write_candidate_atomic,
        _now_iso,
        _ms_to_iso,
    ) = _import_lesson_author_helpers()

    counts = {
        "written": 0,
        "in_db_skipped": 0,
        "exists_skipped": 0,
        "garbage_skipped": 0,
        "malformed_skipped": 0,
    }

    # ── Load inputs ────────────────────────────────────────────
    if verbose:
        print(f"Loading journal:   {journal_path}")
    raw_journal = load_journal(journal_path)

    if verbose:
        print(f"Loading critiques: {critiques_path}")
    raw_critiques = load_critiques(critiques_path)
    critique_index = build_critique_index(raw_critiques)

    already_in_db = get_db_entry_ids(db_path)
    if verbose:
        print(f"Lessons in DB already: {len(already_in_db)}")

    learnings_slice = read_learnings_tail(learnings_path)

    if not dry_run:
        candidate_dir.mkdir(parents=True, exist_ok=True)

    # ── Process each journal row ───────────────────────────────
    for raw in raw_journal:
        try:
            entry = _normalize_journal_row(raw)
        except Exception as exc:
            if verbose:
                print(f"  SKIP malformed row (normalize error): {exc}")
            counts["malformed_skipped"] += 1
            continue

        if not _is_closed_position(entry):
            continue  # open/tick row — skip silently

        entry_id = str(entry.get("entry_id", "") or "")
        if not entry_id:
            if verbose:
                print("  SKIP: closed row missing entry_id")
            counts["garbage_skipped"] += 1
            continue

        if not _is_valid_close(entry):
            if verbose:
                print(f"  SKIP garbage close: entry_id={entry_id!r} "
                      f"entry={entry.get('entry_price')} exit={entry.get('exit_price')} "
                      f"roe={entry.get('roe_pct')}")
            counts["garbage_skipped"] += 1
            continue

        # Idempotency: already in DB
        if entry_id in already_in_db:
            if verbose:
                print(f"  SKIP already-in-db: {entry_id}")
            counts["in_db_skipped"] += 1
            continue

        candidate_path = candidate_dir / _safe_filename(entry_id)

        # Idempotency: candidate file exists
        if candidate_path.exists() and not force:
            if verbose:
                print(f"  SKIP candidate-exists: {candidate_path.name}")
            counts["exists_skipped"] += 1
            continue

        # ── Join critique ──────────────────────────────────────
        critique = find_matching_critique(entry, critique_index)

        # ── Load thesis snapshot ───────────────────────────────
        market = str(entry.get("instrument") or "")
        thesis_snapshot, thesis_snapshot_path = load_thesis_snapshot(market, thesis_backup_dir)

        # ── Build candidate ────────────────────────────────────
        candidate = assemble_candidate(
            entry=entry,
            critique=critique,
            learnings_slice=learnings_slice,
            thesis_snapshot=thesis_snapshot,
            thesis_snapshot_path=thesis_snapshot_path,
            now_iso_fn=_now_iso,
            ms_to_iso_fn=_ms_to_iso,
        )

        if dry_run:
            print(f"\n  [DRY-RUN] Would write: {candidate_path.name}")
            print(f"    market={candidate['market']!r} "
                  f"direction={candidate['direction']!r} "
                  f"pnl={candidate['pnl_usd']:+.2f} "
                  f"roe={candidate['roe_pct']:+.2f}% "
                  f"critique={'yes' if critique else 'none'}")
            counts["written"] += 1
            continue

        # ── Atomic write ───────────────────────────────────────
        try:
            _write_candidate_atomic(candidate_path, candidate)
            if verbose:
                print(f"  WROTE: {candidate_path.name}")
            counts["written"] += 1
        except OSError as exc:
            print(f"  ERROR writing {candidate_path.name}: {exc}", file=sys.stderr)

    return counts


# ---------------------------------------------------------------------------
# CLI entry-point
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Backfill lessons table from existing journal + critiques."
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print what would be done; write nothing.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        dest="force",
        default=False,
        help="Overwrite existing candidate files (default: skip).",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        default=False,
        help="Suppress per-row output.",
    )
    args = parser.parse_args()

    if args.dry_run:
        print("=== DRY-RUN mode — nothing will be written ===\n")

    counts = run_backfill(
        dry_run=args.dry_run,
        force=args.force,
        verbose=not args.quiet,
    )

    label = "Would write" if args.dry_run else "Written"
    print(
        f"\n=== Backfill complete ===\n"
        f"  {label}:          {counts['written']}\n"
        f"  Already-in-DB:   {counts['in_db_skipped']}\n"
        f"  Candidate exists: {counts['exists_skipped']}\n"
        f"  Garbage/invalid:  {counts['garbage_skipped']}\n"
        f"  Malformed rows:   {counts['malformed_skipped']}\n"
    )

    # Print a sample candidate for operator review (first written in dry-run).
    if args.dry_run and counts["written"] > 0:
        print("--- Sample candidate (first trade, truncated) ---")
        (
            _normalize_journal_row,
            _is_closed_position,
            _is_valid_close,
            _safe_filename,
            _write_candidate_atomic,
            _now_iso,
            _ms_to_iso,
        ) = _import_lesson_author_helpers()

        raw_journal = load_journal(JOURNAL_PATH)
        raw_critiques = load_critiques(CRITIQUES_PATH)
        critique_index = build_critique_index(raw_critiques)
        learnings_slice = read_learnings_tail(LEARNINGS_PATH)

        for raw in raw_journal:
            try:
                entry = _normalize_journal_row(raw)
            except Exception:
                continue
            if not _is_closed_position(entry):
                continue
            if not _is_valid_close(entry):
                continue
            entry_id = str(entry.get("entry_id", "") or "")
            if not entry_id:
                continue
            critique = find_matching_critique(entry, critique_index)
            thesis_snapshot, thesis_snapshot_path = load_thesis_snapshot(
                str(entry.get("instrument") or ""), THESIS_BACKUP_DIR
            )
            sample = assemble_candidate(
                entry=entry,
                critique=critique,
                learnings_slice=learnings_slice,
                thesis_snapshot=thesis_snapshot,
                thesis_snapshot_path=thesis_snapshot_path,
                now_iso_fn=_now_iso,
                ms_to_iso_fn=_ms_to_iso,
            )
            # Truncate large fields for display.
            display = dict(sample)
            display.pop("learnings_md_slice", None)
            if "journal_entry" in display:
                je = dict(display["journal_entry"])
                if "thesis_summary" in je and len(str(je["thesis_summary"])) > 80:
                    je["thesis_summary"] = str(je["thesis_summary"])[:80] + "..."
                display["journal_entry"] = je
            print(json.dumps(display, indent=2, default=str))
            break


if __name__ == "__main__":
    main()
