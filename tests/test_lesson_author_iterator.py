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
    catalysts = tmp_path / "data" / "news" / "catalysts.jsonl"

    def make(**overrides) -> LessonAuthorIterator:
        return LessonAuthorIterator(
            config_path=str(overrides.get("config", config)),
            journal_path=str(overrides.get("journal", journal)),
            state_path=str(overrides.get("state", state)),
            candidate_dir=str(overrides.get("candidates", candidates)),
            thesis_backup_dir=str(overrides.get("thesis_backup", thesis_backup)),
            learnings_path=str(overrides.get("learnings", learnings)),
            catalysts_path=str(overrides.get("catalysts", catalysts)),
        )

    def append(*rows):
        with journal.open("a") as f:
            for r in rows:
                f.write(json.dumps(r) + "\n")

    def write_catalysts(*rows):
        catalysts.parent.mkdir(parents=True, exist_ok=True)
        with catalysts.open("w") as f:
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
        "catalysts": catalysts,
        "make": make,
        "append": append,
        "write_catalysts": write_catalysts,
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


# ---------------------------------------------------------------------------
# News context enrichment from catalysts.jsonl
# ---------------------------------------------------------------------------

def _catalyst(
    instruments=("xyz:BRENTOIL",),
    event_date="2026-04-08T18:30:00+00:00",
    severity=4,
    category="geopolitical_strike",
    direction="bull",
    rationale="rule fired",
):
    return {
        "id": f"id-{event_date}",
        "headline_id": "h",
        "instruments": list(instruments),
        "event_date": event_date,
        "category": category,
        "severity": severity,
        "expected_direction": direction,
        "rationale": rationale,
        "created_at": event_date,
    }


class TestNewsContextWindow:
    def test_missing_file_returns_empty(self, workdir):
        it = workdir["make"]()
        out = it._read_catalysts_window(
            market="xyz:BRENTOIL",
            entry_ts_ms=1000,
            close_ts_ms=2000,
        )
        assert out == ""

    def test_no_catalysts_in_window(self, workdir):
        # Catalyst BEFORE the trade window
        workdir["write_catalysts"](
            _catalyst(event_date="2026-04-01T00:00:00+00:00")
        )
        it = workdir["make"]()
        # Trade window is in 2026-04-08
        entry_ms = int(__import__("datetime").datetime(2026, 4, 8, tzinfo=__import__("datetime").timezone.utc).timestamp() * 1000)
        close_ms = entry_ms + 3_600_000
        assert it._read_catalysts_window("xyz:BRENTOIL", entry_ms, close_ms) == ""

    def test_returns_in_window_catalysts(self, workdir):
        from datetime import datetime, timezone
        workdir["write_catalysts"](
            _catalyst(event_date="2026-04-08T18:30:00+00:00", severity=5, category="geopolitical_strike"),
            _catalyst(event_date="2026-04-08T19:00:00+00:00", severity=3, category="trump_oil_announcement"),
            _catalyst(event_date="2026-04-09T01:00:00+00:00", severity=4, category="opec_meeting"),  # outside window
        )
        it = workdir["make"]()
        entry_ms = int(datetime(2026, 4, 8, 18, 0, tzinfo=timezone.utc).timestamp() * 1000)
        close_ms = int(datetime(2026, 4, 8, 22, 0, tzinfo=timezone.utc).timestamp() * 1000)
        out = it._read_catalysts_window("xyz:BRENTOIL", entry_ms, close_ms)
        assert "Catalysts touching xyz:BRENTOIL" in out
        assert "2 matching" in out
        assert "geopolitical_strike" in out
        assert "trump_oil_announcement" in out
        assert "opec_meeting" not in out
        # Severity-DESC ordering
        assert out.index("sev=5") < out.index("sev=3")

    def test_filters_by_market(self, workdir):
        from datetime import datetime, timezone
        workdir["write_catalysts"](
            _catalyst(instruments=["xyz:BRENTOIL"], category="brent_only"),
            _catalyst(instruments=["xyz:GOLD"], category="gold_only"),
        )
        it = workdir["make"]()
        entry_ms = int(datetime(2026, 4, 8, 0, tzinfo=timezone.utc).timestamp() * 1000)
        close_ms = int(datetime(2026, 4, 9, 0, tzinfo=timezone.utc).timestamp() * 1000)
        out = it._read_catalysts_window("xyz:BRENTOIL", entry_ms, close_ms)
        assert "brent_only" in out
        assert "gold_only" not in out

    def test_xyz_prefix_normalisation(self, workdir):
        """Catalysts may store either 'xyz:BRENTOIL' or 'BRENTOIL' — match both."""
        from datetime import datetime, timezone
        workdir["write_catalysts"](
            _catalyst(instruments=["BRENTOIL"], category="bare_form"),
            _catalyst(instruments=["xyz:BRENTOIL"], category="prefixed_form"),
        )
        it = workdir["make"]()
        entry_ms = int(datetime(2026, 4, 8, 0, tzinfo=timezone.utc).timestamp() * 1000)
        close_ms = int(datetime(2026, 4, 9, 0, tzinfo=timezone.utc).timestamp() * 1000)
        # Querying with the prefixed form should still match the bare form
        out = it._read_catalysts_window("xyz:BRENTOIL", entry_ms, close_ms)
        assert "bare_form" in out
        assert "prefixed_form" in out

    def test_invalid_timestamps_returns_empty(self, workdir):
        workdir["write_catalysts"](_catalyst())
        it = workdir["make"]()
        assert it._read_catalysts_window("xyz:BRENTOIL", None, None) == ""
        assert it._read_catalysts_window("xyz:BRENTOIL", "not int", 100) == ""

    def test_close_before_entry_returns_empty(self, workdir):
        workdir["write_catalysts"](_catalyst())
        it = workdir["make"]()
        # close_ms < entry_ms is malformed
        assert it._read_catalysts_window("xyz:BRENTOIL", 2000, 1000) == ""

    def test_max_catalysts_cap(self, workdir):
        from datetime import datetime, timezone
        rows = []
        for i in range(30):
            rows.append(_catalyst(
                event_date=f"2026-04-08T{18 + i // 60:02d}:{i % 60:02d}:00+00:00",
                category=f"cat_{i}",
            ))
        workdir["write_catalysts"](*rows)
        it = workdir["make"]()
        entry_ms = int(datetime(2026, 4, 8, 0, tzinfo=timezone.utc).timestamp() * 1000)
        close_ms = int(datetime(2026, 4, 10, 0, tzinfo=timezone.utc).timestamp() * 1000)
        out = it._read_catalysts_window("xyz:BRENTOIL", entry_ms, close_ms)
        # Default cap is 20
        assert out.count("- sev=") == 20
        assert "20 matching" in out

    def test_malformed_lines_skipped(self, workdir):
        # Mix of bad JSON, valid catalyst, and valid catalyst with bad date
        workdir["catalysts"].parent.mkdir(parents=True, exist_ok=True)
        workdir["catalysts"].write_text(
            "not json\n"
            + json.dumps(_catalyst()) + "\n"
            + json.dumps(_catalyst(event_date="not-a-date")) + "\n"
        )
        from datetime import datetime, timezone
        it = workdir["make"]()
        entry_ms = int(datetime(2026, 4, 8, 0, tzinfo=timezone.utc).timestamp() * 1000)
        close_ms = int(datetime(2026, 4, 9, 0, tzinfo=timezone.utc).timestamp() * 1000)
        out = it._read_catalysts_window("xyz:BRENTOIL", entry_ms, close_ms)
        # Only the one valid in-window catalyst survives
        assert "1 matching" in out

    def test_assemble_request_includes_news_context(self, workdir):
        """End-to-end: a closed-position row produces a candidate file with
        news_context_at_open populated from catalysts.jsonl."""
        workdir["write_catalysts"](
            _catalyst(
                event_date="2026-04-08T18:30:00+00:00",
                severity=5,
                category="physical_damage_facility",
            ),
        )
        # close row whose entry/close timestamps span the catalyst time
        from datetime import datetime, timezone
        entry_ts = int(datetime(2026, 4, 8, 18, 0, tzinfo=timezone.utc).timestamp() * 1000)
        close_ts = int(datetime(2026, 4, 8, 22, 0, tzinfo=timezone.utc).timestamp() * 1000)
        workdir["append"](_close_row(
            entry_id="trade-with-news",
            entry_ts=entry_ts,
            close_ts=close_ts,
            holding_ms=close_ts - entry_ts,
        ))
        it = workdir["make"]()
        it.on_start(_ctx())
        it.tick(_ctx())

        files = list(workdir["candidates"].glob("*.json"))
        assert len(files) == 1
        cand = json.loads(files[0].read_text())
        assert cand["news_context_at_open"]
        assert "physical_damage_facility" in cand["news_context_at_open"]
        assert "sev=5" in cand["news_context_at_open"]
