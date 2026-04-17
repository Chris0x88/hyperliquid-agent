"""Smoke tests for scripts/restore_memory_backup.py.

Covers:
  - --list shows files sorted newest-first
  - restore to empty target succeeds without --force
  - restore to non-empty target without --force is refused (exit 2)
  - restore to non-empty target WITH --force succeeds and saves pre-restore backup
  - --dry-run writes nothing
  - integrity_check is verified on the restored DB
  - row counts are printed for known tables
  - bad/nonexistent --from returns exit 1
"""
from __future__ import annotations

import sqlite3
import sys
import time
from pathlib import Path

import pytest

# Make the project root importable so the script's sys.path manipulation works
# and the helper functions can be imported directly for unit testing.
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from scripts.restore_memory_backup import (  # noqa: E402
    _backup_files,
    _human_size,
    _integrity_check,
    _is_empty_db,
    _row_counts,
    _sha256,
    main,
)


# ── Fixtures ─────────────────────────────────────────────────────────────────


def _make_db(path: Path, rows: int = 3) -> None:
    """Create a tiny SQLite DB with the main-table schema used in production."""
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    try:
        conn.executescript(
            f"""
            CREATE TABLE IF NOT EXISTS lessons  (id INTEGER PRIMARY KEY, summary TEXT);
            CREATE TABLE IF NOT EXISTS events   (id INTEGER PRIMARY KEY, body TEXT);
            CREATE TABLE IF NOT EXISTS learnings(id INTEGER PRIMARY KEY, body TEXT);
            CREATE TABLE IF NOT EXISTS action_log(id INTEGER PRIMARY KEY, msg TEXT);
            CREATE TABLE IF NOT EXISTS account_snapshots(id INTEGER PRIMARY KEY);
            CREATE TABLE IF NOT EXISTS observations(id INTEGER PRIMARY KEY);
            CREATE TABLE IF NOT EXISTS summaries(id INTEGER PRIMARY KEY);
            CREATE TABLE IF NOT EXISTS execution_traces(id INTEGER PRIMARY KEY);
            INSERT INTO lessons  (summary) VALUES {', '.join(f"('lesson {i}')" for i in range(rows))};
            INSERT INTO events   (body)    VALUES ('e1'), ('e2');
            INSERT INTO learnings(body)    VALUES ('l1');
            INSERT INTO action_log(msg)    VALUES {', '.join(f"('act {i}')" for i in range(rows))};
            """
        )
        conn.commit()
    finally:
        conn.close()


def _make_backup_dir(tmp_path: Path, count: int = 3) -> Path:
    """Create count fake backup .db files in tmp_path/backups/ with mtime spread."""
    bd = tmp_path / "backups"
    bd.mkdir()
    for i in range(count):
        p = bd / f"memory-20260101-{i:04d}.db"
        _make_db(p, rows=i + 1)
        # Stagger mtimes so sort is deterministic
        mtime = 1_700_000_000 + i * 3600
        import os
        os.utime(p, (mtime, mtime))
    return bd


# ── Helper unit tests ─────────────────────────────────────────────────────────


class TestHelpers:
    def test_sha256_is_hex_64_chars(self, tmp_path):
        p = tmp_path / "data.bin"
        p.write_bytes(b"hello world")
        h = _sha256(p)
        assert len(h) == 64
        assert all(c in "0123456789abcdef" for c in h)

    def test_human_size(self):
        assert "1.0 B" in _human_size(1)
        assert "KB" in _human_size(2048)
        assert "MB" in _human_size(2 * 1024 * 1024)

    def test_backup_files_sorted_newest_first(self, tmp_path):
        bd = _make_backup_dir(tmp_path, count=3)
        files = _backup_files(bd)
        # Newest (highest mtime) should come first
        assert files[0].name == "memory-20260101-0002.db"
        assert files[-1].name == "memory-20260101-0000.db"

    def test_backup_files_excludes_non_db_files(self, tmp_path):
        bd = tmp_path / "backups"
        bd.mkdir()
        (bd / "memory-20260101-0000.db").write_bytes(b"x")
        (bd / "memory-20260101-0001.db.tmp").write_bytes(b"x")
        (bd / "memory-20260101-0002.db-shm").write_bytes(b"x")
        (bd / "README.txt").write_bytes(b"x")
        files = _backup_files(bd)
        assert len(files) == 1
        assert files[0].name == "memory-20260101-0000.db"

    def test_is_empty_db_true_for_nonexistent(self, tmp_path):
        assert _is_empty_db(tmp_path / "nope.db") is True

    def test_is_empty_db_true_for_zero_bytes(self, tmp_path):
        p = tmp_path / "empty.db"
        p.write_bytes(b"")
        assert _is_empty_db(p) is True

    def test_is_empty_db_false_for_populated(self, tmp_path):
        p = tmp_path / "mem.db"
        _make_db(p)
        assert _is_empty_db(p) is False

    def test_integrity_check_pass(self, tmp_path):
        p = tmp_path / "good.db"
        _make_db(p)
        ok, msg = _integrity_check(p)
        assert ok is True
        assert msg == "ok"

    def test_integrity_check_fail_on_garbage(self, tmp_path):
        p = tmp_path / "bad.db"
        p.write_bytes(b"this is not a sqlite database file at all")
        ok, msg = _integrity_check(p)
        assert ok is False

    def test_row_counts_returns_known_tables(self, tmp_path):
        p = tmp_path / "mem.db"
        _make_db(p, rows=5)
        counts = _row_counts(p)
        assert counts["lessons"] == 5
        assert counts["action_log"] == 5
        assert counts["events"] == 2
        assert counts["learnings"] == 1
        assert counts["observations"] == 0


# ── CLI smoke tests ───────────────────────────────────────────────────────────


class TestCLIRestore:
    """End-to-end tests via main() using a synthetic backup dir."""

    def test_list_exits_zero(self, tmp_path, capsys):
        bd = _make_backup_dir(tmp_path, count=2)
        rc = main(["--backup-dir", str(bd), "--list"])
        assert rc == 0
        out = capsys.readouterr().out
        assert "memory-20260101-0001.db" in out  # newest first

    def test_list_empty_dir_exits_zero(self, tmp_path, capsys):
        bd = tmp_path / "empty_backups"
        bd.mkdir()
        rc = main(["--backup-dir", str(bd), "--list"])
        assert rc == 0

    def test_restore_to_empty_target_no_force(self, tmp_path):
        bd = _make_backup_dir(tmp_path, count=1)
        target = tmp_path / "restored.db"
        assert not target.exists()
        rc = main([
            "--backup-dir", str(bd),
            "--from", "memory-20260101-0000.db",
            "--to", str(target),
        ])
        assert rc == 0
        assert target.exists()
        ok, msg = _integrity_check(target)
        assert ok is True

    def test_restore_to_nonempty_target_without_force_refuses(self, tmp_path, capsys):
        bd = _make_backup_dir(tmp_path, count=2)
        target = tmp_path / "existing.db"
        _make_db(target)
        rc = main([
            "--backup-dir", str(bd),
            "--from", "memory-20260101-0001.db",
            "--to", str(target),
        ])
        assert rc == 2  # user abort
        # Target should be UNCHANGED (original rows intact)
        counts = _row_counts(target)
        assert counts["lessons"] == 3  # from _make_db default rows=3

    def test_restore_to_nonempty_target_with_force_saves_pre_restore(self, tmp_path):
        bd = _make_backup_dir(tmp_path, count=2)
        target = tmp_path / "existing.db"
        _make_db(target, rows=10)  # 10 lessons in "live" DB
        rc = main([
            "--backup-dir", str(bd),
            "--from", "memory-20260101-0001.db",  # 2 rows from _make_backup_dir
            "--to", str(target),
            "--force",
        ])
        assert rc == 0
        # Pre-restore backup must exist.
        # _pre_restore_backup_path appends to target.name so the name is
        # "existing.db.pre-restore-<ts>.db".
        pre_backups = list(tmp_path.glob("existing.db.pre-restore-*.db"))
        assert len(pre_backups) == 1
        # Pre-restore backup should have original 10 rows
        pre_counts = _row_counts(pre_backups[0])
        assert pre_counts["lessons"] == 10
        # Target should have the backup's 2 rows now
        restored_counts = _row_counts(target)
        assert restored_counts["lessons"] == 2

    def test_dry_run_writes_nothing(self, tmp_path):
        bd = _make_backup_dir(tmp_path, count=1)
        target = tmp_path / "never.db"
        rc = main([
            "--backup-dir", str(bd),
            "--from", "memory-20260101-0000.db",
            "--to", str(target),
            "--dry-run",
        ])
        assert rc == 0
        assert not target.exists()  # nothing written

    def test_from_nonexistent_backup_exits_1(self, tmp_path, capsys):
        bd = _make_backup_dir(tmp_path, count=1)
        target = tmp_path / "out.db"
        rc = main([
            "--backup-dir", str(bd),
            "--from", "memory-does-not-exist.db",
            "--to", str(target),
        ])
        assert rc == 1

    def test_row_counts_shown_after_restore(self, tmp_path, capsys):
        bd = _make_backup_dir(tmp_path, count=1)
        target = tmp_path / "out.db"
        main([
            "--backup-dir", str(bd),
            "--from", "memory-20260101-0000.db",
            "--to", str(target),
        ])
        out = capsys.readouterr().out
        assert "lessons" in out
        assert "action_log" in out

    def test_pass_line_printed_on_success(self, tmp_path, capsys):
        bd = _make_backup_dir(tmp_path, count=1)
        target = tmp_path / "out.db"
        rc = main([
            "--backup-dir", str(bd),
            "--from", "memory-20260101-0000.db",
            "--to", str(target),
        ])
        assert rc == 0
        out = capsys.readouterr().out
        assert "PASS" in out
