"""Tests for scripts/backfill_lessons.py.

Covers: dry-run mode, idempotent skip (in-db + candidate-exists),
join logic (match / window-miss / no-critique), malformed rows,
and the full write path against a temp DB.

All tests use synthetic in-memory fixtures — no real journal.jsonl or memory.db
is touched.
"""
from __future__ import annotations

import json
import os
import sqlite3
import sys
import tempfile
import textwrap
import time
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Ensure agent-cli root is on sys.path before importing anything.
# ---------------------------------------------------------------------------

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from scripts.backfill_lessons import (
    CRITIQUE_JOIN_WINDOW_MS,
    assemble_candidate,
    build_critique_index,
    find_matching_critique,
    get_db_entry_ids,
    load_critiques,
    load_journal,
    run_backfill,
)


# ---------------------------------------------------------------------------
# Tiny helpers re-exported from the daemon iterator so tests use the real code.
# ---------------------------------------------------------------------------

from daemon.iterators.lesson_author import (
    _normalize_journal_row,
    _is_closed_position,
    _is_valid_close,
    _now_iso,
    _ms_to_iso,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_trade(
    *,
    trade_id: str = "042",
    instrument: str = "xyz:CL",
    direction: str = "LONG",
    entry_price: float = 95.0,
    exit_price: float = 93.0,
    pnl: float = -20.0,
    roe_pct: float = -2.1,
    leverage: float = 20.0,
    timestamp_open: str = "2026-04-09T17:37:46Z",
    timestamp_close: str = "2026-04-09T17:40:07Z",
    thesis_summary: str = "WTI LONG thesis",
    conviction_at_close: float = 0.7,
) -> dict:
    """Synthetic trade_id-schema journal row (matching real journal.jsonl shape)."""
    return {
        "trade_id": trade_id,
        "timestamp_open": timestamp_open,
        "timestamp_close": timestamp_close,
        "instrument": instrument,
        "direction": direction,
        "size": 10.825,
        "entry_price": entry_price,
        "exit_price": exit_price,
        "pnl": pnl,
        "roe_pct": roe_pct,
        "leverage": leverage,
        "liquidation_price": 88.0,
        "stop_loss": None,
        "take_profit": None,
        "thesis_summary": thesis_summary,
        "conviction_at_close": conviction_at_close,
        "account_equity": 374.8,
    }


def _make_critique(
    *,
    instrument: str = "xyz:CL",
    direction: str = "long",
    entry_price: float = 95.0,
    entry_ts_ms: int = 1775749486242,  # 2026-04-09T17:44:46Z-ish
    overall_label: str = "MIXED ENTRY",
) -> dict:
    """Synthetic entry_critique row."""
    return {
        "schema_version": 1,
        "kind": "entry_critique",
        "created_at": "2026-04-09T17:44:46Z",
        "instrument": instrument,
        "direction": direction,
        "entry_price": entry_price,
        "entry_qty": 10.0,
        "entry_ts_ms": entry_ts_ms,
        "leverage": 20.0,
        "grade": {
            "overall_label": overall_label,
            "pass_count": 1,
            "warn_count": 3,
            "fail_count": 0,
        },
        "signals": {},
        "degraded": {},
    }


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as f:
        for row in rows:
            f.write(json.dumps(row) + "\n")


def _make_db_with_lesson(path: Path, journal_entry_id: str) -> None:
    """Create a SQLite DB with one lesson row referencing the given entry_id."""
    from common.memory import log_lesson
    lesson = {
        "created_at": "2026-04-09T05:00:00Z",
        "trade_closed_at": "2026-04-09T04:55:00Z",
        "market": "xyz:CL",
        "direction": "long",
        "signal_source": "manual",
        "lesson_type": "entry_timing",
        "outcome": "loss",
        "pnl_usd": -20.0,
        "roe_pct": -2.1,
        "holding_ms": 141_000,
        "summary": "synthetic lesson",
        "body_full": "synthetic body",
        "tags": [],
        "journal_entry_id": journal_entry_id,
    }
    log_lesson(lesson, db_path=str(path))


# ---------------------------------------------------------------------------
# 1. Dry-run mode: nothing is written, counts reflect what WOULD happen.
# ---------------------------------------------------------------------------

class TestDryRun:
    def test_dry_run_writes_nothing(self, tmp_path):
        journal_path = tmp_path / "journal.jsonl"
        _write_jsonl(journal_path, [_make_trade(trade_id="001")])

        candidate_dir = tmp_path / "candidates"
        db_path = tmp_path / "memory.db"

        counts = run_backfill(
            journal_path=journal_path,
            critiques_path=tmp_path / "critiques.jsonl",  # does not exist
            candidate_dir=candidate_dir,
            db_path=db_path,
            learnings_path=tmp_path / "learnings.md",
            thesis_backup_dir=tmp_path / "thesis_backup",
            dry_run=True,
            force=False,
            verbose=False,
        )

        assert counts["written"] == 1, "dry-run should count the trade as 'would write'"
        # No files should have been created
        assert not candidate_dir.exists() or list(candidate_dir.iterdir()) == []

    def test_dry_run_skips_open_positions(self, tmp_path):
        """A row without exit_price is not a closed position — must be ignored."""
        open_trade = {
            "trade_id": "002",
            "timestamp_open": "2026-04-09T10:00:00Z",
            "instrument": "xyz:CL",
            "direction": "LONG",
            "entry_price": 95.0,
            # no timestamp_close, no exit_price, no pnl
        }
        journal_path = tmp_path / "journal.jsonl"
        _write_jsonl(journal_path, [open_trade])

        counts = run_backfill(
            journal_path=journal_path,
            critiques_path=tmp_path / "c.jsonl",
            candidate_dir=tmp_path / "cand",
            db_path=tmp_path / "mem.db",
            learnings_path=tmp_path / "l.md",
            thesis_backup_dir=tmp_path / "tb",
            dry_run=True,
            force=False,
            verbose=False,
        )
        assert counts["written"] == 0

    def test_dry_run_skips_garbage_closes(self, tmp_path):
        """exit_price=0 must be rejected by _is_valid_close."""
        bad_trade = _make_trade(trade_id="003", exit_price=0.0)
        journal_path = tmp_path / "journal.jsonl"
        _write_jsonl(journal_path, [bad_trade])

        counts = run_backfill(
            journal_path=journal_path,
            critiques_path=tmp_path / "c.jsonl",
            candidate_dir=tmp_path / "cand",
            db_path=tmp_path / "mem.db",
            learnings_path=tmp_path / "l.md",
            thesis_backup_dir=tmp_path / "tb",
            dry_run=True,
            force=False,
            verbose=False,
        )
        assert counts["garbage_skipped"] == 1
        assert counts["written"] == 0


# ---------------------------------------------------------------------------
# 2. Idempotency: skip if already in DB or candidate file exists.
# ---------------------------------------------------------------------------

class TestIdempotency:
    def test_skips_if_already_in_db(self, tmp_path):
        trade = _make_trade(trade_id="010")
        # Normalise to get the canonical entry_id the DB would store.
        norm = _normalize_journal_row(trade)
        entry_id = str(norm.get("entry_id", ""))

        journal_path = tmp_path / "journal.jsonl"
        _write_jsonl(journal_path, [trade])

        db_path = tmp_path / "memory.db"
        _make_db_with_lesson(db_path, entry_id)

        counts = run_backfill(
            journal_path=journal_path,
            critiques_path=tmp_path / "c.jsonl",
            candidate_dir=tmp_path / "cand",
            db_path=db_path,
            learnings_path=tmp_path / "l.md",
            thesis_backup_dir=tmp_path / "tb",
            dry_run=False,
            force=False,
            verbose=False,
        )
        assert counts["in_db_skipped"] == 1
        assert counts["written"] == 0

    def test_skips_if_candidate_file_exists(self, tmp_path):
        trade = _make_trade(trade_id="011")
        norm = _normalize_journal_row(trade)
        entry_id = str(norm.get("entry_id", ""))

        journal_path = tmp_path / "journal.jsonl"
        _write_jsonl(journal_path, [trade])

        candidate_dir = tmp_path / "cand"
        candidate_dir.mkdir(parents=True)
        # Pre-create the candidate file so backfill sees it as existing.
        safe = entry_id.replace(":", "_").replace("/", "_").replace(" ", "_")
        (candidate_dir / f"{safe}.json").write_text("{}")

        counts = run_backfill(
            journal_path=journal_path,
            critiques_path=tmp_path / "c.jsonl",
            candidate_dir=candidate_dir,
            db_path=tmp_path / "memory.db",
            learnings_path=tmp_path / "l.md",
            thesis_backup_dir=tmp_path / "tb",
            dry_run=False,
            force=False,
            verbose=False,
        )
        assert counts["exists_skipped"] == 1
        assert counts["written"] == 0

    def test_force_overwrites_existing_candidate(self, tmp_path):
        trade = _make_trade(trade_id="012")
        norm = _normalize_journal_row(trade)
        entry_id = str(norm.get("entry_id", ""))

        journal_path = tmp_path / "journal.jsonl"
        _write_jsonl(journal_path, [trade])

        candidate_dir = tmp_path / "cand"
        candidate_dir.mkdir(parents=True)
        safe = entry_id.replace(":", "_").replace("/", "_").replace(" ", "_")
        existing = candidate_dir / f"{safe}.json"
        existing.write_text("{}")

        counts = run_backfill(
            journal_path=journal_path,
            critiques_path=tmp_path / "c.jsonl",
            candidate_dir=candidate_dir,
            db_path=tmp_path / "memory.db",
            learnings_path=tmp_path / "l.md",
            thesis_backup_dir=tmp_path / "tb",
            dry_run=False,
            force=True,
            verbose=False,
        )
        assert counts["written"] == 1
        assert counts["exists_skipped"] == 0
        # File must now contain a real candidate (not the stub "{}").
        data = json.loads(existing.read_text())
        assert data.get("kind") == "lesson_candidate"


# ---------------------------------------------------------------------------
# 3. Join logic: critique matching by (instrument, entry_ts +/- 60s).
# ---------------------------------------------------------------------------

class TestJoinLogic:
    def test_matches_critique_within_window(self):
        """Critique whose entry_ts_ms is within 60s of the trade's entry_ts
        should be returned."""
        # trade entry_ts for 2026-04-09T17:37:46Z  → 1775749066000
        trade_entry_ts_ms = 1_775_749_066_000
        # Critique 30 s later → within the 60s window.
        critique = _make_critique(
            instrument="xyz:CL",
            entry_ts_ms=trade_entry_ts_ms + 30_000,
        )
        index = build_critique_index([critique])

        # Build a fake normalised entry with known entry_ts.
        entry = {
            "entry_id": "t",
            "instrument": "xyz:CL",
            "entry_ts": trade_entry_ts_ms,
        }
        result = find_matching_critique(entry, index)
        assert result is not None
        assert result["grade"]["overall_label"] == "MIXED ENTRY"

    def test_no_match_outside_window(self):
        """Critique more than 60s away must NOT be returned."""
        trade_entry_ts_ms = 1_775_749_066_000
        critique = _make_critique(
            instrument="xyz:CL",
            entry_ts_ms=trade_entry_ts_ms + CRITIQUE_JOIN_WINDOW_MS + 1,
        )
        index = build_critique_index([critique])
        entry = {
            "entry_id": "t",
            "instrument": "xyz:CL",
            "entry_ts": trade_entry_ts_ms,
        }
        result = find_matching_critique(entry, index)
        assert result is None

    def test_instrument_prefix_normalised(self):
        """Critique with 'xyz:CL' instrument must match a trade with 'CL'."""
        trade_entry_ts_ms = 1_775_749_066_000
        critique = _make_critique(
            instrument="xyz:CL",
            entry_ts_ms=trade_entry_ts_ms + 5_000,
        )
        index = build_critique_index([critique])
        # Trade uses bare 'CL' without prefix.
        entry = {
            "entry_id": "t",
            "instrument": "CL",
            "entry_ts": trade_entry_ts_ms,
        }
        result = find_matching_critique(entry, index)
        assert result is not None

    def test_no_critique_for_different_instrument(self):
        """Critique for SILVER must not match a CL trade."""
        trade_entry_ts_ms = 1_775_749_066_000
        critique = _make_critique(
            instrument="xyz:SILVER",
            entry_ts_ms=trade_entry_ts_ms + 1_000,
        )
        index = build_critique_index([critique])
        entry = {
            "entry_id": "t",
            "instrument": "xyz:CL",
            "entry_ts": trade_entry_ts_ms,
        }
        result = find_matching_critique(entry, index)
        assert result is None

    def test_returns_closest_when_multiple_candidates(self):
        """Given two critiques in-window, the closest one (by ms) must win."""
        trade_entry_ts_ms = 1_775_749_066_000
        near = _make_critique(instrument="xyz:CL", entry_ts_ms=trade_entry_ts_ms + 5_000,
                              overall_label="NEAR")
        far = _make_critique(instrument="xyz:CL", entry_ts_ms=trade_entry_ts_ms + 45_000,
                             overall_label="FAR")
        index = build_critique_index([near, far])
        entry = {
            "entry_id": "t",
            "instrument": "xyz:CL",
            "entry_ts": trade_entry_ts_ms,
        }
        result = find_matching_critique(entry, index)
        assert result is not None
        assert result["grade"]["overall_label"] == "NEAR"


# ---------------------------------------------------------------------------
# 4. Missing critique: no critique available — candidate still written.
# ---------------------------------------------------------------------------

class TestMissingCritique:
    def test_candidate_written_without_critique(self, tmp_path):
        trade = _make_trade(trade_id="020")
        journal_path = tmp_path / "journal.jsonl"
        _write_jsonl(journal_path, [trade])

        candidate_dir = tmp_path / "cand"

        counts = run_backfill(
            journal_path=journal_path,
            critiques_path=tmp_path / "no_critiques.jsonl",  # does not exist
            candidate_dir=candidate_dir,
            db_path=tmp_path / "memory.db",
            learnings_path=tmp_path / "l.md",
            thesis_backup_dir=tmp_path / "tb",
            dry_run=False,
            force=False,
            verbose=False,
        )
        assert counts["written"] == 1

        # Find the written file.
        files = list(candidate_dir.iterdir())
        assert len(files) == 1
        data = json.loads(files[0].read_text())
        assert data["kind"] == "lesson_candidate"
        # No critique attached.
        assert "entry_critique" not in data["journal_entry"]

    def test_candidate_includes_critique_when_matched(self, tmp_path):
        """When a critique matches, the candidate's journal_entry contains it."""
        # Trade opened at 2026-04-09T17:37:46Z
        trade = _make_trade(trade_id="021", timestamp_open="2026-04-09T17:37:46Z")
        norm = _normalize_journal_row(trade)
        trade_entry_ts = int(norm.get("entry_ts", 0))

        # Critique 10 s after open — within window.
        critique = _make_critique(
            instrument="xyz:CL",
            entry_ts_ms=trade_entry_ts + 10_000,
            overall_label="BAD ENTRY",
        )

        journal_path = tmp_path / "journal.jsonl"
        critiques_path = tmp_path / "critiques.jsonl"
        _write_jsonl(journal_path, [trade])
        _write_jsonl(critiques_path, [critique])

        candidate_dir = tmp_path / "cand"

        run_backfill(
            journal_path=journal_path,
            critiques_path=critiques_path,
            candidate_dir=candidate_dir,
            db_path=tmp_path / "memory.db",
            learnings_path=tmp_path / "l.md",
            thesis_backup_dir=tmp_path / "tb",
            dry_run=False,
            force=False,
            verbose=False,
        )

        files = list(candidate_dir.iterdir())
        assert len(files) == 1
        data = json.loads(files[0].read_text())
        assert "entry_critique" in data["journal_entry"]
        assert data["journal_entry"]["entry_critique"]["grade"]["overall_label"] == "BAD ENTRY"


# ---------------------------------------------------------------------------
# 5. Malformed rows: JSON parse errors and missing required fields.
# ---------------------------------------------------------------------------

class TestMalformedRows:
    def test_malformed_json_line_skipped(self, tmp_path):
        """A non-JSON line in journal.jsonl must not crash backfill."""
        journal_path = tmp_path / "journal.jsonl"
        journal_path.write_text(
            "not valid json\n"
            + json.dumps(_make_trade(trade_id="030")) + "\n"
        )

        counts = run_backfill(
            journal_path=journal_path,
            critiques_path=tmp_path / "c.jsonl",
            candidate_dir=tmp_path / "cand",
            db_path=tmp_path / "memory.db",
            learnings_path=tmp_path / "l.md",
            thesis_backup_dir=tmp_path / "tb",
            dry_run=False,
            force=False,
            verbose=False,
        )
        # The valid trade should still be written.
        assert counts["written"] == 1

    def test_row_missing_exit_price_is_skipped(self, tmp_path):
        """A closed-looking row without exit_price must be skipped."""
        bad = {
            "trade_id": "031",
            "timestamp_open": "2026-04-09T10:00:00Z",
            "timestamp_close": "2026-04-09T10:02:00Z",
            "instrument": "xyz:CL",
            "direction": "LONG",
            "entry_price": 95.0,
            # no exit_price, no pnl
        }
        journal_path = tmp_path / "journal.jsonl"
        _write_jsonl(journal_path, [bad])

        counts = run_backfill(
            journal_path=journal_path,
            critiques_path=tmp_path / "c.jsonl",
            candidate_dir=tmp_path / "cand",
            db_path=tmp_path / "memory.db",
            learnings_path=tmp_path / "l.md",
            thesis_backup_dir=tmp_path / "tb",
            dry_run=False,
            force=False,
            verbose=False,
        )
        # Not counted as garbage (it never passed _is_closed_position).
        assert counts["written"] == 0
        assert counts["garbage_skipped"] == 0  # silently skipped as open/tick row

    def test_both_canonical_and_legacy_rows_processed(self, tmp_path):
        """A mix of canonical (entry_id) and trade_id schema rows must both work."""
        canonical = {
            "entry_id": "BTC-smoketest-2026-04-09",
            "instrument": "BTC",
            "direction": "long",
            "entry_price": 94000.0,
            "exit_price": 94800.0,
            "pnl": 800.0,
            "roe_pct": 0.85,
            "holding_ms": 14_400_000,
            "entry_source": "thesis_driven",
            "entry_ts": 1_775_681_063_146,
            "close_ts": 1_775_695_463_146,
        }
        legacy = _make_trade(trade_id="032")

        journal_path = tmp_path / "journal.jsonl"
        _write_jsonl(journal_path, [canonical, legacy])

        counts = run_backfill(
            journal_path=journal_path,
            critiques_path=tmp_path / "c.jsonl",
            candidate_dir=tmp_path / "cand",
            db_path=tmp_path / "memory.db",
            learnings_path=tmp_path / "l.md",
            thesis_backup_dir=tmp_path / "tb",
            dry_run=False,
            force=False,
            verbose=False,
        )
        assert counts["written"] == 2


# ---------------------------------------------------------------------------
# 6. Candidate schema validation.
# ---------------------------------------------------------------------------

class TestCandidateSchema:
    def test_candidate_has_required_fields(self, tmp_path):
        trade = _make_trade(trade_id="040")
        journal_path = tmp_path / "journal.jsonl"
        _write_jsonl(journal_path, [trade])
        candidate_dir = tmp_path / "cand"

        run_backfill(
            journal_path=journal_path,
            critiques_path=tmp_path / "c.jsonl",
            candidate_dir=candidate_dir,
            db_path=tmp_path / "memory.db",
            learnings_path=tmp_path / "l.md",
            thesis_backup_dir=tmp_path / "tb",
            dry_run=False,
            force=False,
            verbose=False,
        )

        files = list(candidate_dir.iterdir())
        assert len(files) == 1
        data = json.loads(files[0].read_text())

        required = [
            "schema_version", "kind", "created_at", "backfill",
            "journal_entry", "thesis_snapshot", "thesis_snapshot_path",
            "learnings_md_slice", "news_context_at_open",
            "market", "direction", "signal_source", "pnl_usd",
            "roe_pct", "holding_ms", "trade_closed_at", "journal_entry_id",
        ]
        for field in required:
            assert field in data, f"missing field: {field}"

        assert data["schema_version"] == 1
        assert data["kind"] == "lesson_candidate"
        assert data["backfill"] is True
        assert data["market"] == "xyz:CL"
        assert data["direction"] == "long"  # normalised from "LONG"
        assert data["pnl_usd"] == -20.0
        assert data["roe_pct"] == -2.1

    def test_candidate_filename_is_filesystem_safe(self, tmp_path):
        """Candidate filenames must not contain colon (common on xyz: instruments)."""
        trade = _make_trade(trade_id="041")
        journal_path = tmp_path / "journal.jsonl"
        _write_jsonl(journal_path, [trade])
        candidate_dir = tmp_path / "cand"

        run_backfill(
            journal_path=journal_path,
            critiques_path=tmp_path / "c.jsonl",
            candidate_dir=candidate_dir,
            db_path=tmp_path / "memory.db",
            learnings_path=tmp_path / "l.md",
            thesis_backup_dir=tmp_path / "tb",
            dry_run=False,
            force=False,
            verbose=False,
        )
        files = list(candidate_dir.iterdir())
        assert len(files) == 1
        # No colon in filename (unsafe on macOS/Windows)
        assert ":" not in files[0].name
