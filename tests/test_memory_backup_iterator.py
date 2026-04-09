"""Tests for MemoryBackupIterator — closes the memory.db SPOF.

Covers:
  - Kill switch (disabled config → tick is no-op)
  - Interval gating (back-to-back ticks don't backup twice)
  - Atomic backup writes a valid SQLite snapshot identical to source
  - Integrity check on snapshot
  - Daily / weekly slot promotion (idempotent — only first snapshot of
    the day/week populates the slot)
  - Retention rotation (drops oldest hourly past keep_hourly window)
  - Missing source DB → graceful skip
  - Bad config JSON → defaults to enabled
"""
from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path
from unittest.mock import patch

import pytest

from cli.daemon.iterators.memory_backup import (
    DAILY_TAG,
    HOURLY_PREFIX,
    HOURLY_SUFFIX,
    WEEKLY_TAG,
    MemoryBackupIterator,
)


# ---------- Fixtures ----------


def _make_source_db(path: Path) -> None:
    """Create a tiny SQLite DB with a couple of rows for backup tests."""
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    try:
        conn.executescript(
            """
            CREATE TABLE lessons (id INTEGER PRIMARY KEY, summary TEXT);
            INSERT INTO lessons (summary) VALUES ('first lesson'), ('second lesson');
            """
        )
        conn.commit()
    finally:
        conn.close()


def _make_iter(tmp_path: Path, **cfg_overrides) -> MemoryBackupIterator:
    """Build an iterator pointed at tmp_path, with config written to disk."""
    src = tmp_path / "memory.db"
    backup_dir = tmp_path / "backups"
    cfg_path = tmp_path / "memory_backup.json"
    cfg = {
        "enabled": True,
        "interval_hours": 1,
        "source_path": str(src),
        "backup_dir": str(backup_dir),
        "keep_hourly": 24,
        "keep_daily": 7,
        "keep_weekly": 4,
        "verify_integrity": True,
    }
    cfg.update(cfg_overrides)
    cfg_path.write_text(json.dumps(cfg))
    return MemoryBackupIterator(
        config_path=str(cfg_path),
        source_path=str(src),
        backup_dir=str(backup_dir),
    )


# ---------- Kill switch ----------


class TestKillSwitch:
    def test_disabled_config_skips_tick(self, tmp_path):
        src = tmp_path / "memory.db"
        _make_source_db(src)
        it = _make_iter(tmp_path, enabled=False)
        it.on_start(ctx=None)
        it.tick(ctx=None)
        # No backups written
        backup_dir = tmp_path / "backups"
        assert not backup_dir.exists() or not any(backup_dir.iterdir())

    def test_missing_config_defaults_enabled(self, tmp_path):
        src = tmp_path / "memory.db"
        _make_source_db(src)
        backup_dir = tmp_path / "backups"
        # Point at a config path that does NOT exist
        it = MemoryBackupIterator(
            config_path=str(tmp_path / "nope.json"),
            source_path=str(src),
            backup_dir=str(backup_dir),
        )
        it.on_start(ctx=None)
        # Force tick to pass interval gate
        it._last_run = -1e9
        it.tick(ctx=None)
        snapshots = list(backup_dir.glob(f"{HOURLY_PREFIX}*{HOURLY_SUFFIX}"))
        assert len(snapshots) >= 1

    def test_bad_config_json_defaults_enabled(self, tmp_path):
        src = tmp_path / "memory.db"
        _make_source_db(src)
        backup_dir = tmp_path / "backups"
        cfg_path = tmp_path / "memory_backup.json"
        cfg_path.write_text("{not json")  # malformed
        it = MemoryBackupIterator(
            config_path=str(cfg_path),
            source_path=str(src),
            backup_dir=str(backup_dir),
        )
        it.on_start(ctx=None)
        assert it._enabled is True


# ---------- Interval gating ----------


class TestIntervalGating:
    def test_back_to_back_ticks_only_back_up_once(self, tmp_path):
        src = tmp_path / "memory.db"
        _make_source_db(src)
        it = _make_iter(tmp_path)
        it.on_start(ctx=None)
        it._last_run = -1e9  # force first run
        it.tick(ctx=None)
        first_count = len(list((tmp_path / "backups").glob(f"{HOURLY_PREFIX}*{HOURLY_SUFFIX}")))
        # Second tick should be gated
        it.tick(ctx=None)
        second_count = len(list((tmp_path / "backups").glob(f"{HOURLY_PREFIX}*{HOURLY_SUFFIX}")))
        assert second_count == first_count


# ---------- Atomic backup correctness ----------


class TestBackupCorrectness:
    def test_snapshot_is_valid_sqlite(self, tmp_path):
        src = tmp_path / "memory.db"
        _make_source_db(src)
        it = _make_iter(tmp_path)
        it.on_start(ctx=None)
        result = it.run_once()
        assert result["integrity_ok"] is True
        snapshot = Path(result["snapshot"])
        # Open the snapshot and verify the test data made it across
        conn = sqlite3.connect(str(snapshot))
        try:
            rows = conn.execute("SELECT summary FROM lessons ORDER BY id").fetchall()
        finally:
            conn.close()
        assert rows == [("first lesson",), ("second lesson",)]

    def test_snapshot_size_matches_source_order_of_magnitude(self, tmp_path):
        src = tmp_path / "memory.db"
        _make_source_db(src)
        it = _make_iter(tmp_path)
        it.on_start(ctx=None)
        result = it.run_once()
        snapshot_size = Path(result["snapshot"]).stat().st_size
        source_size = src.stat().st_size
        # Online backup may differ slightly in page count but should be
        # the same order of magnitude (within 4x).
        assert snapshot_size > 0
        assert snapshot_size <= source_size * 4

    def test_no_tmp_files_left_behind(self, tmp_path):
        src = tmp_path / "memory.db"
        _make_source_db(src)
        it = _make_iter(tmp_path)
        it.on_start(ctx=None)
        it.run_once()
        tmps = list((tmp_path / "backups").glob("*.tmp"))
        assert tmps == []


# ---------- Integrity check ----------


class TestIntegrityCheck:
    def test_integrity_failure_keeps_snapshot_does_not_rotate(self, tmp_path):
        src = tmp_path / "memory.db"
        _make_source_db(src)
        it = _make_iter(tmp_path)
        it.on_start(ctx=None)
        with patch.object(MemoryBackupIterator, "_verify", return_value=False):
            result = it.run_once()
        assert result["integrity_ok"] is False
        # Snapshot still exists for forensic recovery
        assert Path(result["snapshot"]).exists()
        # Did NOT rotate (no `rotated_removed` key returned on bad path)
        assert "rotated_removed" not in result

    def test_verify_integrity_can_be_disabled(self, tmp_path):
        src = tmp_path / "memory.db"
        _make_source_db(src)
        it = _make_iter(tmp_path, verify_integrity=False)
        it.on_start(ctx=None)
        result = it.run_once()
        assert result["integrity_ok"] is True  # short-circuited to True


# ---------- Promotion to daily / weekly slots ----------


class TestPromotion:
    def test_first_snapshot_of_day_promotes_to_daily(self, tmp_path):
        src = tmp_path / "memory.db"
        _make_source_db(src)
        it = _make_iter(tmp_path)
        it.on_start(ctx=None)
        result = it.run_once()
        assert result["promotions"]["daily"] is True
        daily_files = list((tmp_path / "backups").glob(f"*{DAILY_TAG}{HOURLY_SUFFIX}"))
        assert len(daily_files) == 1

    def test_second_snapshot_same_day_does_not_re_promote(self, tmp_path):
        src = tmp_path / "memory.db"
        _make_source_db(src)
        it = _make_iter(tmp_path)
        it.on_start(ctx=None)
        it.run_once()
        result2 = it.run_once()
        assert result2["promotions"]["daily"] is False
        daily_files = list((tmp_path / "backups").glob(f"*{DAILY_TAG}{HOURLY_SUFFIX}"))
        assert len(daily_files) == 1  # still just one

    def test_first_snapshot_of_week_promotes_to_weekly(self, tmp_path):
        src = tmp_path / "memory.db"
        _make_source_db(src)
        it = _make_iter(tmp_path)
        it.on_start(ctx=None)
        result = it.run_once()
        assert result["promotions"]["weekly"] is True
        weekly_files = list((tmp_path / "backups").glob(f"*{WEEKLY_TAG}{HOURLY_SUFFIX}"))
        assert len(weekly_files) == 1


# ---------- Rotation ----------


class TestRotation:
    def test_rotation_drops_oldest_hourly_past_keep_window(self, tmp_path):
        src = tmp_path / "memory.db"
        _make_source_db(src)
        it = _make_iter(tmp_path, keep_hourly=3, keep_daily=99, keep_weekly=99)
        it.on_start(ctx=None)
        backup_dir = tmp_path / "backups"
        backup_dir.mkdir(exist_ok=True)
        # Plant 5 fake hourly files with sortable names — oldest two should drop
        for i, ts in enumerate(["20260101-0900", "20260101-1000", "20260101-1100", "20260101-1200", "20260101-1300"]):
            (backup_dir / f"{HOURLY_PREFIX}{ts}{HOURLY_SUFFIX}").write_bytes(b"fake")
        removed = it._rotate()
        assert removed == 2
        remaining = sorted(p.name for p in backup_dir.glob(f"{HOURLY_PREFIX}*{HOURLY_SUFFIX}"))
        # Oldest two (0900, 1000) gone; newest three (1100, 1200, 1300) kept
        assert "memory-20260101-0900.db" not in remaining
        assert "memory-20260101-1000.db" not in remaining
        assert "memory-20260101-1100.db" in remaining
        assert "memory-20260101-1300.db" in remaining

    def test_rotation_does_not_touch_daily_or_weekly_slots(self, tmp_path):
        src = tmp_path / "memory.db"
        _make_source_db(src)
        it = _make_iter(tmp_path, keep_hourly=1)
        it.on_start(ctx=None)
        backup_dir = tmp_path / "backups"
        backup_dir.mkdir(exist_ok=True)
        # Mix of hourly + daily + weekly
        (backup_dir / f"{HOURLY_PREFIX}20260101-0900{HOURLY_SUFFIX}").write_bytes(b"h1")
        (backup_dir / f"{HOURLY_PREFIX}20260101-1000{HOURLY_SUFFIX}").write_bytes(b"h2")
        (backup_dir / f"{HOURLY_PREFIX}20260101{DAILY_TAG}{HOURLY_SUFFIX}").write_bytes(b"d1")
        (backup_dir / f"{HOURLY_PREFIX}2026W01{WEEKLY_TAG}{HOURLY_SUFFIX}").write_bytes(b"w1")
        it._rotate()
        # Daily + weekly preserved
        assert (backup_dir / f"{HOURLY_PREFIX}20260101{DAILY_TAG}{HOURLY_SUFFIX}").exists()
        assert (backup_dir / f"{HOURLY_PREFIX}2026W01{WEEKLY_TAG}{HOURLY_SUFFIX}").exists()


# ---------- Missing source ----------


class TestMissingSource:
    def test_missing_source_db_skips_gracefully(self, tmp_path):
        # No memory.db created
        it = _make_iter(tmp_path)
        it.on_start(ctx=None)
        result = it.run_once()
        assert result == {"skipped": True, "reason": "source_missing"}


# ---------- Tier registration ----------


class TestTierRegistration:
    def test_memory_backup_in_all_three_tiers(self):
        from cli.daemon.tiers import TIER_ITERATORS

        for tier in ("watch", "rebalance", "opportunistic"):
            assert "memory_backup" in TIER_ITERATORS[tier], f"missing from {tier}"
