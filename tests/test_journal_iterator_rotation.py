"""Tests for the H5 daily rotation + retention pruning in JournalIterator.

Closes the active growth concern from the 2026-04-07 verification ledger:
ticks.jsonl was growing at ~1 MB/day with no rotation logic. The iterator
now writes to date-stamped ticks-YYYYMMDD.jsonl files and prunes anything
older than RETENTION_DAYS days.
"""
from __future__ import annotations

import json
import os
import time
from decimal import Decimal
from pathlib import Path

import pytest

from daemon.context import TickContext
from daemon.iterators.journal import JournalIterator, RETENTION_DAYS
from exchange.risk_manager import RiskGate


def _ctx(tick: int = 1) -> TickContext:
    c = TickContext()
    c.timestamp = int(time.time() * 1000)
    c.tick_number = tick
    c.balances = {"USDC": Decimal("10000")}
    c.prices = {"BTC": Decimal("100")}
    c.risk_gate = RiskGate.OPEN
    return c


def _make_iterator(tmp_path) -> tuple[JournalIterator, Path]:
    """Construct a JournalIterator rooted at tmp_path."""
    it = JournalIterator(data_dir=str(tmp_path))
    it.on_start(_ctx())
    return it, tmp_path / "journal"


# ---------------------------------------------------------------------------
# Daily rotation tests
# ---------------------------------------------------------------------------


class TestDailyRotation:
    def test_writes_to_date_stamped_file(self, tmp_path):
        """Tick snapshots land in ticks-YYYYMMDD.jsonl, not the legacy file."""
        it, journal_dir = _make_iterator(tmp_path)
        it.tick(_ctx(1))

        today = time.strftime("%Y%m%d", time.gmtime())
        expected = journal_dir / f"ticks-{today}.jsonl"
        assert expected.exists(), f"Expected {expected.name} to exist"

        legacy = journal_dir / "ticks.jsonl"
        assert not legacy.exists(), "Legacy ticks.jsonl must not be created by new code"

    def test_multiple_ticks_append_to_same_day_file(self, tmp_path):
        """Multiple ticks within the same UTC day all land in one file."""
        it, journal_dir = _make_iterator(tmp_path)
        for i in range(5):
            it.tick(_ctx(tick=i + 1))

        today = time.strftime("%Y%m%d", time.gmtime())
        target = journal_dir / f"ticks-{today}.jsonl"
        assert target.exists()
        with target.open() as f:
            lines = f.readlines()
        assert len(lines) == 5
        # Each line is valid JSON with the expected shape
        for i, line in enumerate(lines):
            row = json.loads(line)
            assert row["tick"] == i + 1
            assert "timestamp" in row
            assert row["risk_gate"] == RiskGate.OPEN.value

    def test_legacy_ticks_jsonl_logged_but_left_alone(self, tmp_path, caplog):
        """If a pre-rotation ticks.jsonl exists, on_start logs it but doesn't touch it."""
        journal_dir = tmp_path / "journal"
        journal_dir.mkdir(parents=True)
        legacy = journal_dir / "ticks.jsonl"
        legacy.write_text('{"tick": 999}\n')

        with caplog.at_level("INFO", logger="daemon.journal"):
            it = JournalIterator(data_dir=str(tmp_path))
            it.on_start(_ctx())

        # Legacy file is preserved untouched
        assert legacy.exists()
        assert legacy.read_text() == '{"tick": 999}\n'
        # Log mentions the legacy file
        assert any("legacy ticks.jsonl" in record.message for record in caplog.records)


# ---------------------------------------------------------------------------
# Retention pruning tests
# ---------------------------------------------------------------------------


class TestRetentionPrune:
    def test_prunes_files_older_than_retention(self, tmp_path):
        """Files with mtime older than RETENTION_DAYS are deleted."""
        journal_dir = tmp_path / "journal"
        journal_dir.mkdir(parents=True)
        old_file = journal_dir / "ticks-20200101.jsonl"
        old_file.write_text('{"tick": 1}\n')
        # Set mtime to 30 days ago
        thirty_days_ago = time.time() - (30 * 86_400)
        os.utime(old_file, (thirty_days_ago, thirty_days_ago))

        it = JournalIterator(data_dir=str(tmp_path))
        it._prune_old_journals()

        assert not old_file.exists()

    def test_keeps_files_within_retention(self, tmp_path):
        """Files newer than RETENTION_DAYS are kept."""
        journal_dir = tmp_path / "journal"
        journal_dir.mkdir(parents=True)
        recent_file = journal_dir / "ticks-20260401.jsonl"
        recent_file.write_text('{"tick": 1}\n')
        # Set mtime to 5 days ago
        five_days_ago = time.time() - (5 * 86_400)
        os.utime(recent_file, (five_days_ago, five_days_ago))

        it = JournalIterator(data_dir=str(tmp_path))
        it._prune_old_journals()

        assert recent_file.exists()

    def test_pruner_does_not_touch_legacy_ticks_jsonl(self, tmp_path):
        """The legacy ticks.jsonl file is not date-stamped → never pruned by this code."""
        journal_dir = tmp_path / "journal"
        journal_dir.mkdir(parents=True)
        legacy = journal_dir / "ticks.jsonl"
        legacy.write_text('{"old": true}\n')
        # Make it ancient
        ancient = time.time() - (365 * 86_400)
        os.utime(legacy, (ancient, ancient))

        it = JournalIterator(data_dir=str(tmp_path))
        it._prune_old_journals()

        assert legacy.exists()
        assert legacy.read_text() == '{"old": true}\n'

    def test_pruner_does_not_touch_other_files(self, tmp_path):
        """Files that don't match ticks-*.jsonl glob are not pruned."""
        journal_dir = tmp_path / "journal"
        journal_dir.mkdir(parents=True)
        unrelated = journal_dir / "summary-20200101.jsonl"
        unrelated.write_text('{"summary": "old"}\n')
        ancient = time.time() - (365 * 86_400)
        os.utime(unrelated, (ancient, ancient))

        it = JournalIterator(data_dir=str(tmp_path))
        it._prune_old_journals()

        assert unrelated.exists()

    def test_prune_runs_at_most_once_per_day(self, tmp_path):
        """The per-tick prune trigger only fires when the UTC day changes."""
        it, journal_dir = _make_iterator(tmp_path)
        # Capture initial state — on_start already pruned once
        initial_last_prune = it._last_prune_day

        # First real tick on the same day
        it.tick(_ctx(tick=1))
        first_prune_day = it._last_prune_day
        # Should be set to today's date string
        today = time.strftime("%Y%m%d", time.gmtime())
        assert first_prune_day == today

        # Second tick on the same day — should still be the same date string
        # (we can't check that prune wasn't called by side-effects easily, but
        # the day cache prevents the file walk)
        it.tick(_ctx(tick=2))
        assert it._last_prune_day == today

    def test_full_lifecycle_through_iterator(self, tmp_path):
        """End-to-end: ancient file is pruned during a normal tick cycle."""
        it, journal_dir = _make_iterator(tmp_path)
        # Plant an ancient file
        ancient_file = journal_dir / "ticks-20200101.jsonl"
        ancient_file.write_text('{"old": true}\n')
        os.utime(ancient_file, (time.time() - (RETENTION_DAYS + 1) * 86_400,) * 2)

        # Force re-prune by clearing the day cache (simulates next-day tick)
        it._last_prune_day = "19990101"

        # Tick — should write today's file AND prune the ancient one
        it.tick(_ctx(tick=1))

        assert not ancient_file.exists()
        today = time.strftime("%Y%m%d", time.gmtime())
        assert (journal_dir / f"ticks-{today}.jsonl").exists()
