"""Tests for cli/daemon/iterators/lesson_author.py — wedge 5.

The iterator is intentionally pure I/O (no AI). It watches journal.jsonl for
closed-position rows, assembles a verbatim LessonAuthorRequest dict, and
writes it as a candidate file under data/daemon/lesson_candidates/. The
"agent authors the lesson and persists to memory.db" step is a future wedge.

These tests cover:
- on_start lifecycle (config load, dir creation, state restore)
- tick: detects closes, writes candidates, dedupes
- garbage filtering (Bug A pattern from 2026-04-08)
- cursor / state file roundtrip
- thesis snapshot lookup via H6 backup dir
- learnings.md tail slicing
- kill switch
"""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from cli.daemon.iterators.lesson_author import (
    LessonAuthorIterator,
    _is_closed_position,
    _is_valid_close,
    _safe_filename,
)


def _ctx() -> MagicMock:
    """Minimal TickContext stand-in — the iterator never reads from it."""
    return MagicMock()


def _close_row(**overrides) -> dict:
    base = {
        "entry_id": "xyz:BRENTOIL-1712633100000",
        "instrument": "xyz:BRENTOIL",
        "direction": "long",
        "entry_price": 89.5,
        "exit_price": 91.2,
        "pnl": 17.0,
        "roe_pct": 1.9,
        "holding_ms": 3_600_000,
        "entry_source": "thesis_driven",
        "entry_signal_score": 0.0,
        "close_reason": "take_profit",
        "entry_ts": 1712629500000,
        "close_ts": 1712633100000,
        "entry_reasoning": "Entered xyz:BRENTOIL long via thesis_driven",
        "exit_reasoning": "Take-profit hit",
        "signal_quality": "good",
        "retrospective": "Worked as planned.",
    }
    base.update(overrides)
    return base


def _tick_snapshot() -> dict:
    """Non-close row that the iterator must ignore."""
    return {
        "timestamp": 123,
        "tick": 1,
        "balances": {},
        "prices": {},
        "n_positions": 0,
    }


@pytest.fixture
def workdir(tmp_path):
    """Provide a hermetic workdir with all expected subdirs and a builder
    that constructs an iterator pointed at it."""
    journal = tmp_path / "data" / "research" / "journal.jsonl"
    journal.parent.mkdir(parents=True)
    journal.touch()

    state = tmp_path / "data" / "daemon" / "lesson_author_state.json"
    state.parent.mkdir(parents=True, exist_ok=True)

    candidates = tmp_path / "data" / "daemon" / "lesson_candidates"
    thesis_backup = tmp_path / "data" / "thesis_backup"
    learnings = tmp_path / "data" / "research" / "learnings.md"
    config = tmp_path / "data" / "config" / "lesson_author.json"

    def make(**overrides) -> LessonAuthorIterator:
        return LessonAuthorIterator(
            config_path=str(overrides.get("config", config)),
            journal_path=str(overrides.get("journal", journal)),
            state_path=str(overrides.get("state", state)),
            candidate_dir=str(overrides.get("candidates", candidates)),
            thesis_backup_dir=str(overrides.get("thesis_backup", thesis_backup)),
            learnings_path=str(overrides.get("learnings", learnings)),
        )

    def append(*rows):
        with journal.open("a") as f:
            for r in rows:
                f.write(json.dumps(r) + "\n")

    return {
        "tmp": tmp_path,
        "journal": journal,
        "state": state,
        "candidates": candidates,
        "thesis_backup": thesis_backup,
        "learnings": learnings,
        "config": config,
        "make": make,
        "append": append,
    }


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------

class TestPureHelpers:
    def test_is_closed_position_true(self):
        assert _is_closed_position(_close_row()) is True

    def test_is_closed_position_false_for_tick_snapshot(self):
        assert _is_closed_position(_tick_snapshot()) is False

    def test_is_valid_close_happy_path(self):
        assert _is_valid_close(_close_row()) is True

    def test_is_valid_close_rejects_zero_exit(self):
        assert _is_valid_close(_close_row(exit_price=0)) is False

    def test_is_valid_close_rejects_zero_entry(self):
        assert _is_valid_close(_close_row(entry_price=0)) is False

    def test_is_valid_close_rejects_extreme_roe(self):
        assert _is_valid_close(_close_row(roe_pct=5000)) is False

    def test_is_valid_close_rejects_negative_holding(self):
        assert _is_valid_close(_close_row(holding_ms=-100)) is False

    def test_is_valid_close_handles_garbage_types(self):
        assert _is_valid_close(_close_row(exit_price="not a number")) is False

    def test_safe_filename_replaces_colons(self):
        assert _safe_filename("xyz:BRENTOIL-123") == "xyz_BRENTOIL-123.json"

    def test_safe_filename_replaces_slashes_and_spaces(self):
        assert _safe_filename("a/b c") == "a_b_c.json"


# ---------------------------------------------------------------------------
# Lifecycle
# ---------------------------------------------------------------------------

class TestLifecycle:
    def test_on_start_creates_candidate_dir(self, workdir):
        it = workdir["make"]()
        it.on_start(_ctx())
        assert workdir["candidates"].exists()

    def test_on_start_loads_existing_state(self, workdir):
        workdir["state"].write_text(json.dumps({
            "last_offset": 42,
            "processed_ids": ["xyz:BRENTOIL-1", "xyz:BRENTOIL-2"],
        }))
        it = workdir["make"]()
        it.on_start(_ctx())
        assert it._last_offset == 42
        assert it._processed_ids == {"xyz:BRENTOIL-1", "xyz:BRENTOIL-2"}

    def test_on_start_handles_missing_state(self, workdir):
        it = workdir["make"]()
        it.on_start(_ctx())
        assert it._last_offset == 0
        assert it._processed_ids == set()

    def test_on_start_recovers_from_corrupt_state(self, workdir):
        workdir["state"].write_text("not json")
        it = workdir["make"]()
        it.on_start(_ctx())
        assert it._last_offset == 0
        assert it._processed_ids == set()

    def test_disabled_kill_switch(self, workdir):
        workdir["config"].parent.mkdir(parents=True, exist_ok=True)
        workdir["config"].write_text(json.dumps({"enabled": False}))
        it = workdir["make"]()
        it.on_start(_ctx())
        # Should NOT create candidates dir when disabled
        workdir["append"](_close_row())
        it.tick(_ctx())
        assert not any(workdir["candidates"].glob("*.json"))


# ---------------------------------------------------------------------------
# Tick: candidate writing
# ---------------------------------------------------------------------------

class TestTickCandidateWriting:
    def test_writes_candidate_for_close(self, workdir):
        workdir["append"](_close_row(entry_id="xyz:BRENTOIL-1"))
        it = workdir["make"]()
        it.on_start(_ctx())
        it.tick(_ctx())

        files = list(workdir["candidates"].glob("*.json"))
        assert len(files) == 1
        assert files[0].name == "xyz_BRENTOIL-1.json"

    def test_candidate_content_is_complete(self, workdir):
        workdir["append"](_close_row(entry_id="xyz:BRENTOIL-1"))
        it = workdir["make"]()
        it.on_start(_ctx())
        it.tick(_ctx())

        files = list(workdir["candidates"].glob("*.json"))
        candidate = json.loads(files[0].read_text())

        assert candidate["schema_version"] == 1
        assert candidate["kind"] == "lesson_candidate"
        assert candidate["market"] == "xyz:BRENTOIL"
        assert candidate["direction"] == "long"
        assert candidate["signal_source"] == "thesis_driven"
        assert candidate["pnl_usd"] == 17.0
        assert candidate["roe_pct"] == 1.9
        assert candidate["holding_ms"] == 3_600_000
        assert candidate["journal_entry_id"] == "xyz:BRENTOIL-1"
        # Verbatim journal entry preserved
        assert candidate["journal_entry"]["entry_price"] == 89.5
        assert candidate["journal_entry"]["exit_price"] == 91.2
        # ISO 8601 timestamp present
        assert candidate["trade_closed_at"].endswith("Z")
        assert "created_at" in candidate

    def test_ignores_tick_snapshots(self, workdir):
        workdir["append"](_tick_snapshot(), _tick_snapshot())
        it = workdir["make"]()
        it.on_start(_ctx())
        it.tick(_ctx())
        assert not any(workdir["candidates"].glob("*.json"))

    def test_ignores_malformed_json(self, workdir):
        workdir["journal"].write_text("not json\n" + json.dumps(_close_row()) + "\n")
        it = workdir["make"]()
        it.on_start(_ctx())
        it.tick(_ctx())
        # The valid row should still write a candidate
        files = list(workdir["candidates"].glob("*.json"))
        assert len(files) == 1

    def test_skips_garbage_close_zero_exit(self, workdir):
        workdir["append"](_close_row(exit_price=0, entry_id="xyz:BRENTOIL-bad"))
        it = workdir["make"]()
        it.on_start(_ctx())
        it.tick(_ctx())
        assert not any(workdir["candidates"].glob("*.json"))
        # Marked processed so we don't re-evaluate next tick
        assert "xyz:BRENTOIL-bad" in it._processed_ids

    def test_writes_one_per_close(self, workdir):
        workdir["append"](
            _close_row(entry_id="a"),
            _close_row(entry_id="b"),
            _close_row(entry_id="c"),
        )
        it = workdir["make"]()
        it.on_start(_ctx())
        it.tick(_ctx())
        assert len(list(workdir["candidates"].glob("*.json"))) == 3


# ---------------------------------------------------------------------------
# Dedup + cursor
# ---------------------------------------------------------------------------

class TestDedupAndCursor:
    def test_dedup_via_processed_ids_set(self, workdir):
        workdir["append"](_close_row(entry_id="dup"))
        it = workdir["make"]()
        it.on_start(_ctx())
        it.tick(_ctx())
        # Append the SAME entry id again (e.g. duplicate row)
        workdir["append"](_close_row(entry_id="dup"))
        it.tick(_ctx())
        files = list(workdir["candidates"].glob("*.json"))
        assert len(files) == 1

    def test_dedup_via_existing_candidate_file(self, workdir):
        """Even if processed_ids is empty (fresh daemon run), an existing
        candidate file on disk causes the row to be skipped."""
        workdir["append"](_close_row(entry_id="abc"))
        # First run writes the candidate
        it1 = workdir["make"]()
        it1.on_start(_ctx())
        it1.tick(_ctx())
        # Second run starts with empty processed_ids and should not re-write
        workdir["state"].unlink()
        # Truncate journal so second iterator re-reads from offset 0 and sees the row again
        workdir["journal"].write_text(json.dumps(_close_row(entry_id="abc")) + "\n")
        it2 = workdir["make"]()
        it2.on_start(_ctx())
        # Pretend processed_ids was lost
        it2._processed_ids = set()
        it2.tick(_ctx())
        files = list(workdir["candidates"].glob("*.json"))
        assert len(files) == 1

    def test_cursor_advances_after_tick(self, workdir):
        workdir["append"](_close_row(entry_id="a"))
        it = workdir["make"]()
        it.on_start(_ctx())
        offset_before = it._last_offset
        it.tick(_ctx())
        assert it._last_offset > offset_before

    def test_cursor_persists_to_state_file(self, workdir):
        workdir["append"](_close_row(entry_id="persist-1"))
        it = workdir["make"]()
        it.on_start(_ctx())
        it.tick(_ctx())
        # State file should now exist with updated offset
        state = json.loads(workdir["state"].read_text())
        assert state["last_offset"] > 0
        assert "persist-1" in state["processed_ids"]

    def test_cursor_resets_on_truncation(self, workdir):
        workdir["append"](_close_row(entry_id="a"))
        it = workdir["make"]()
        it.on_start(_ctx())
        it.tick(_ctx())
        # Truncate journal — file shrinks
        workdir["journal"].write_text("")
        # Make offset clearly past EOF
        it._last_offset = 10000
        it.tick(_ctx())
        assert it._last_offset == 0  # reset

    def test_processed_ids_capped_at_1000(self, workdir):
        """State file should not grow unbounded."""
        it = workdir["make"]()
        it.on_start(_ctx())
        for i in range(2000):
            it._processed_ids.add(f"id-{i:05d}")
        it._save_state()
        state = json.loads(workdir["state"].read_text())
        assert len(state["processed_ids"]) == 1000


# ---------------------------------------------------------------------------
# Thesis snapshot lookup
# ---------------------------------------------------------------------------

class TestThesisSnapshotLookup:
    def test_no_backup_dir_returns_none(self, workdir):
        it = workdir["make"]()
        snap, path = it._load_thesis_snapshot("xyz:BRENTOIL", "long")
        assert snap is None
        assert path is None

    def test_finds_matching_backup(self, workdir):
        workdir["thesis_backup"].mkdir(parents=True, exist_ok=True)
        backup = workdir["thesis_backup"] / "xyz_brentoil_state.json"
        backup.write_text(json.dumps({
            "market": "xyz:BRENTOIL",
            "direction": "long",
            "conviction": 0.7,
        }))
        it = workdir["make"]()
        snap, path = it._load_thesis_snapshot("xyz:BRENTOIL", "long")
        assert snap is not None
        assert snap["conviction"] == 0.7
        assert path == str(backup)

    def test_skips_wrong_market(self, workdir):
        workdir["thesis_backup"].mkdir(parents=True, exist_ok=True)
        (workdir["thesis_backup"] / "xyz_gold_state.json").write_text(json.dumps({
            "market": "xyz:GOLD",
            "direction": "long",
        }))
        it = workdir["make"]()
        snap, path = it._load_thesis_snapshot("xyz:BRENTOIL", "long")
        assert snap is None


# ---------------------------------------------------------------------------
# learnings.md tail
# ---------------------------------------------------------------------------

class TestLearningsTail:
    def test_missing_file_returns_empty(self, workdir):
        it = workdir["make"]()
        assert it._read_learnings_tail() == ""

    def test_short_file_returned_in_full(self, workdir):
        workdir["learnings"].parent.mkdir(parents=True, exist_ok=True)
        workdir["learnings"].write_text("short content")
        it = workdir["make"]()
        assert it._read_learnings_tail() == "short content"

    def test_long_file_truncated_to_tail(self, workdir):
        workdir["learnings"].parent.mkdir(parents=True, exist_ok=True)
        workdir["learnings"].write_text("x" * 5000)
        it = workdir["make"]()
        out = it._read_learnings_tail(max_chars=2000)
        assert out.startswith("... [truncated]")
        # Tail size approximately matches the cap
        assert 1900 < len(out) < 2200


# ---------------------------------------------------------------------------
# Tier registration
# ---------------------------------------------------------------------------

class TestRegistration:
    def test_lesson_author_in_all_three_tiers(self):
        from cli.daemon.tiers import TIER_ITERATORS
        for tier in ("watch", "rebalance", "opportunistic"):
            assert "lesson_author" in TIER_ITERATORS[tier], (
                f"lesson_author missing from {tier} tier"
            )
