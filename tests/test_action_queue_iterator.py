"""Tests for ActionQueueIterator — the daily nudge sweep.

Covers:
  - Kill switch (disabled config → tick is no-op)
  - Missing config file → defaults to enabled
  - Daily interval gating (back-to-back ticks don't double-nudge)
  - Auto-update of lesson_approval_queue.context["pending_count"] from memory.db
  - Auto-update of backup_health_check.last_done_ts from newest backup mtime
  - run_once with ctx posts a single Alert summarising all overdue items
  - run_once with ctx=None does not mark anything nudged (script mode)
  - Nudge cooldown: second run_once inside 24h produces no alert
  - State is saved atomically after each run
  - Graceful handling of missing memory.db / missing backup dir
"""
from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path

import pytest

from cli.daemon.context import TickContext
from cli.daemon.iterators.action_queue import ActionQueueIterator
from engines.learning.action_queue import ActionQueue


# ── Fixtures ─────────────────────────────────────────────────────────────


def _make_memory_db(path: Path, *, pending: int = 0, reviewed: int = 0, rejected: int = 0) -> None:
    """Create a minimal lessons table with the requested counts."""
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    try:
        conn.executescript(
            """
            CREATE TABLE lessons (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                summary TEXT,
                reviewed_by_chris INTEGER NOT NULL DEFAULT 0
            );
            """
        )
        for _ in range(pending):
            conn.execute("INSERT INTO lessons (summary, reviewed_by_chris) VALUES ('p', 0)")
        for _ in range(reviewed):
            conn.execute("INSERT INTO lessons (summary, reviewed_by_chris) VALUES ('r', 1)")
        for _ in range(rejected):
            conn.execute("INSERT INTO lessons (summary, reviewed_by_chris) VALUES ('x', -1)")
        conn.commit()
    finally:
        conn.close()


def _make_backup_file(backup_dir: Path, *, age_seconds: float = 300.0) -> Path:
    """Create a .db file in backup_dir with mtime `age_seconds` in the past."""
    backup_dir.mkdir(parents=True, exist_ok=True)
    path = backup_dir / f"memory-snap-{int(time.time())}.db"
    path.write_bytes(b"SQLite format 3\x00" + b"\x00" * 100)
    mtime = time.time() - age_seconds
    import os
    os.utime(path, (mtime, mtime))
    return path


def _make_iter(tmp_path: Path, **cfg_overrides) -> ActionQueueIterator:
    """Build an iterator pointed at tmp_path with an optional config."""
    state_path = tmp_path / "action_queue.jsonl"
    memory_db = tmp_path / "memory.db"
    backup_dir = tmp_path / "backups"
    cfg_path = tmp_path / "action_queue.json"
    cfg = {"enabled": True, "interval_hours": 24}
    cfg.update(cfg_overrides)
    cfg_path.write_text(json.dumps(cfg))
    return ActionQueueIterator(
        config_path=str(cfg_path),
        state_path=str(state_path),
        memory_db_path=str(memory_db),
        backup_dir=str(backup_dir),
    )


def _make_ctx() -> TickContext:
    """A minimal TickContext with an empty alerts list."""
    return TickContext(timestamp=int(time.time() * 1000), tick_number=1)


# ── Kill switch ─────────────────────────────────────────────────────────


class TestKillSwitch:
    def test_disabled_config_tick_is_noop(self, tmp_path):
        it = _make_iter(tmp_path, enabled=False)
        it.on_start(ctx=_make_ctx())
        # Force interval gate to fire
        it._last_run = -1e9
        ctx = _make_ctx()
        it.tick(ctx=ctx)
        assert ctx.alerts == []
        # State file should NOT have been written
        state = tmp_path / "action_queue.jsonl"
        assert not state.exists()

    def test_missing_config_defaults_enabled(self, tmp_path):
        state_path = tmp_path / "action_queue.jsonl"
        it = ActionQueueIterator(
            config_path=str(tmp_path / "nope.json"),  # missing
            state_path=str(state_path),
            memory_db_path=str(tmp_path / "memory.db"),
            backup_dir=str(tmp_path / "backups"),
        )
        it.on_start(ctx=_make_ctx())
        assert it._enabled is True

    def test_bad_config_json_defaults_enabled(self, tmp_path):
        cfg_path = tmp_path / "action_queue.json"
        cfg_path.write_text("{not json")
        state_path = tmp_path / "action_queue.jsonl"
        it = ActionQueueIterator(
            config_path=str(cfg_path),
            state_path=str(state_path),
            memory_db_path=str(tmp_path / "memory.db"),
            backup_dir=str(tmp_path / "backups"),
        )
        it.on_start(ctx=_make_ctx())
        assert it._enabled is True


# ── Interval gating ─────────────────────────────────────────────────────


class TestIntervalGating:
    def test_back_to_back_ticks_only_fire_once(self, tmp_path):
        it = _make_iter(tmp_path, interval_hours=24)
        it.on_start(ctx=_make_ctx())

        ctx1 = _make_ctx()
        it._last_run = -1e9  # force first run through the gate
        it.tick(ctx=ctx1)
        first_alert_count = len(ctx1.alerts)
        assert first_alert_count >= 1  # default seed list is all overdue

        ctx2 = _make_ctx()
        it.tick(ctx=ctx2)  # immediately after → interval gate blocks it
        assert ctx2.alerts == []


# ── Auto-update ─────────────────────────────────────────────────────────


class TestAutoUpdate:
    def test_pending_lesson_count_from_memory_db(self, tmp_path):
        _make_memory_db(tmp_path / "memory.db", pending=7, reviewed=3, rejected=2)
        it = _make_iter(tmp_path)
        it.on_start(ctx=_make_ctx())

        it._auto_update_items(now_ts=time.time())
        item = it._queue.get("lesson_approval_queue")
        assert item is not None
        assert item.context.get("pending_count") == 7

    def test_pending_count_missing_db_leaves_context_alone(self, tmp_path):
        # No memory.db at all
        it = _make_iter(tmp_path)
        it.on_start(ctx=_make_ctx())
        before = dict(it._queue.get("lesson_approval_queue").context)
        it._auto_update_items(now_ts=time.time())
        after = dict(it._queue.get("lesson_approval_queue").context)
        assert before == after

    def test_backup_health_check_auto_done_when_recent_backup(self, tmp_path):
        _make_backup_file(tmp_path / "backups", age_seconds=60)  # 1 min old
        it = _make_iter(tmp_path)
        it.on_start(ctx=_make_ctx())
        assert it._queue.get("backup_health_check").last_done_ts == 0.0
        it._auto_update_items(now_ts=time.time())
        new_ts = it._queue.get("backup_health_check").last_done_ts
        assert new_ts > 0  # marked as done

    def test_backup_health_check_stale_backup_does_not_auto_done(self, tmp_path):
        _make_backup_file(tmp_path / "backups", age_seconds=6 * 3600)  # 6h old
        it = _make_iter(tmp_path)
        it.on_start(ctx=_make_ctx())
        it._auto_update_items(now_ts=time.time())
        assert it._queue.get("backup_health_check").last_done_ts == 0.0

    def test_backup_dir_missing_is_graceful(self, tmp_path):
        it = _make_iter(tmp_path)  # no backup_dir yet
        it.on_start(ctx=_make_ctx())
        it._auto_update_items(now_ts=time.time())  # must not raise


# ── run_once behavior ──────────────────────────────────────────────────


class TestRunOnce:
    def test_posts_single_alert_with_all_overdue(self, tmp_path):
        it = _make_iter(tmp_path)
        it.on_start(ctx=_make_ctx())
        ctx = _make_ctx()
        result = it.run_once(ctx=ctx)
        assert len(ctx.alerts) == 1
        alert = ctx.alerts[0]
        assert alert.source == "action_queue"
        assert "Action queue" in alert.message
        assert result["overdue_count"] == len(result["nudged"])
        # At least brutal_review and feedback_review should be in the nudge
        assert "brutal_review" in alert.data["overdue_ids"]
        assert "feedback_review" in alert.data["overdue_ids"]

    def test_second_run_within_cooldown_posts_no_alert(self, tmp_path):
        it = _make_iter(tmp_path)
        it.on_start(ctx=_make_ctx())
        it.run_once(ctx=_make_ctx())  # first pass marks everything nudged

        ctx2 = _make_ctx()
        result2 = it.run_once(ctx=ctx2)
        assert ctx2.alerts == []
        assert result2["nudged"] == []

    def test_ctx_none_does_not_mark_nudged(self, tmp_path):
        it = _make_iter(tmp_path)
        it.on_start(ctx=_make_ctx())
        it.run_once(ctx=None)
        # No items should have last_nudged_ts set
        for item in it._queue.items:
            assert item.last_nudged_ts == 0.0

    def test_threshold_item_respects_memory_db_pending_count(self, tmp_path):
        # 10 pending lessons >> threshold of 5 → overdue
        _make_memory_db(tmp_path / "memory.db", pending=10)
        it = _make_iter(tmp_path)
        it.on_start(ctx=_make_ctx())
        ctx = _make_ctx()
        it.run_once(ctx=ctx)
        assert ctx.alerts
        assert "lesson_approval_queue" in ctx.alerts[0].data["overdue_ids"]

    def test_threshold_item_below_count_not_overdue(self, tmp_path):
        _make_memory_db(tmp_path / "memory.db", pending=2)  # below threshold
        it = _make_iter(tmp_path)
        it.on_start(ctx=_make_ctx())
        ctx = _make_ctx()
        it.run_once(ctx=ctx)
        # lesson_approval_queue not in the overdue list
        assert "lesson_approval_queue" not in ctx.alerts[0].data["overdue_ids"]

    def test_state_is_persisted_across_instances(self, tmp_path):
        it1 = _make_iter(tmp_path)
        it1.on_start(ctx=_make_ctx())
        it1.run_once(ctx=_make_ctx())

        # Rebuild a fresh iterator pointed at the same state path
        it2 = _make_iter(tmp_path)
        it2.on_start(ctx=_make_ctx())
        # Every non-per-session seed item should have a nudged timestamp
        nudged = [i for i in it2._queue.items if i.last_nudged_ts > 0]
        assert nudged

    def test_no_overdue_items_produces_no_alert(self, tmp_path):
        it = _make_iter(tmp_path)
        it.on_start(ctx=_make_ctx())
        # Mark every overdue item as done NOW
        now = time.time()
        for item in it._queue.items:
            it._queue.mark_done(item.id, now_ts=now)
        it._queue.save()
        # run_once reloads from disk? No — it uses in-memory queue. Fine.
        ctx = _make_ctx()
        it.run_once(ctx=ctx)
        assert ctx.alerts == []


# ── State file ──────────────────────────────────────────────────────────


class TestStateFile:
    def test_state_file_is_jsonl(self, tmp_path):
        it = _make_iter(tmp_path)
        it.on_start(ctx=_make_ctx())
        it.run_once(ctx=_make_ctx())
        state_path = tmp_path / "action_queue.jsonl"
        assert state_path.exists()
        lines = [line for line in state_path.read_text().splitlines() if line.strip()]
        assert lines  # non-empty
        for line in lines:
            row = json.loads(line)  # every line is valid JSON
            assert "id" in row
            assert "kind" in row
            assert "cadence_days" in row
