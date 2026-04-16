"""ActionQueueIterator — once-per-day sweep of the "things Chris should do" ledger.

Runs inside the daemon clock and:

  1. Reads state from ``data/research/action_queue.jsonl`` (via
     ``modules.action_queue.ActionQueue``).
  2. Auto-updates fields on a subset of items by inspecting the system:
     - ``lesson_approval_queue.context["pending_count"]`` from a direct
       SQL count of ``lessons`` with ``reviewed_by_chris == 0``.
     - ``backup_health_check.last_done_ts`` from the mtime of the newest
       file in ``data/memory/backups/`` (if a recent backup exists, the
       health check is effectively "done" implicitly).
  3. Calls ``evaluate()`` to find items that are overdue and have NOT
     been nudged in the past 24h.
  4. Posts a Telegram digest via ``ctx.alerts`` if anything is overdue.
     The TelegramIterator handles rate-limiting, dedup, and network I/O.
  5. Marks the nudged items' ``last_nudged_ts`` so they don't fire again
     until the cooldown expires.
  6. Saves state atomically.

Tick cadence: one evaluation per ``interval_hours`` hours (default 24h).
Back-to-back ticks inside that window are no-ops. This matches how the
other heartbeat-style iterators (memory_backup, autoresearch) gate their
real work behind a monotonic wall-clock timer.

Kill switch: ``data/config/action_queue.json`` → ``{"enabled": false}``.
Default ON. If the config file is missing, the iterator runs at its
default cadence.

Read-only against every data store it touches except the state JSONL.
Safe in every tier (WATCH / REBALANCE / OPPORTUNISTIC) because it never
queues orders and never modifies positions, thesis, or lessons.
"""
from __future__ import annotations

import json
import logging
import sqlite3
import time
from pathlib import Path
from typing import Any, Optional

from cli.daemon.context import Alert, TickContext
from engines.learning.action_queue import (
    DEFAULT_STATE_PATH,
    ActionQueue,
    format_nudge_telegram,
)

log = logging.getLogger("daemon.action_queue")

DEFAULT_CONFIG_PATH = "data/config/action_queue.json"
DEFAULT_MEMORY_DB = "data/memory/memory.db"
DEFAULT_BACKUP_DIR = "data/memory/backups"
DEFAULT_INTERVAL_HOURS = 24


class ActionQueueIterator:
    """Once-per-day nudge sweep."""

    name = "action_queue"

    def __init__(
        self,
        config_path: str = DEFAULT_CONFIG_PATH,
        state_path: str = DEFAULT_STATE_PATH,
        memory_db_path: str = DEFAULT_MEMORY_DB,
        backup_dir: str = DEFAULT_BACKUP_DIR,
    ):
        self._config_path = Path(config_path)
        self._state_path = Path(state_path)
        self._memory_db_path = Path(memory_db_path)
        self._backup_dir = Path(backup_dir)
        self._enabled: bool = True
        self._interval_s: int = DEFAULT_INTERVAL_HOURS * 3600
        self._last_run: float = 0.0
        self._run_count: int = 0
        self._queue: ActionQueue = ActionQueue(state_path=str(self._state_path))

    # ── Lifecycle ────────────────────────────────────────────

    def on_start(self, ctx: TickContext) -> None:
        self._reload_config()
        if not self._enabled:
            log.info("ActionQueueIterator disabled via config — no-op")
            return
        try:
            self._queue.load()
        except Exception as e:
            log.warning("ActionQueue: failed to load state %s: %s — starting fresh",
                        self._state_path, e)
            self._queue = ActionQueue(state_path=str(self._state_path))
            self._queue.load()
        log.info(
            "ActionQueueIterator ready (interval=%ds, state=%s, items=%d)",
            self._interval_s,
            self._state_path,
            len(self._queue.items),
        )

    def tick(self, ctx: TickContext) -> None:
        self._reload_config()
        if not self._enabled:
            return
        now = time.monotonic()
        if now - self._last_run < self._interval_s:
            return
        self._last_run = now
        self._run_count += 1

        try:
            self.run_once(ctx=ctx)
        except Exception as e:  # pragma: no cover — defensive only
            log.warning("ActionQueue: tick failed: %s", e)

    def on_stop(self) -> None:
        log.info("ActionQueueIterator stopped after %d runs", self._run_count)

    # ── Public single-shot entry point ───────────────────────

    def run_once(self, ctx: Optional[TickContext] = None) -> dict[str, Any]:
        """Evaluate the queue, auto-update a few items, post a nudge alert
        if anything is overdue, and save state.

        Returns a stats dict for logging / tests.
        """
        now_ts = time.time()
        self._auto_update_items(now_ts=now_ts)

        overdue = self._queue.evaluate(now_ts=now_ts)
        nudged_ids: list[str] = []

        if overdue and ctx is not None:
            message = format_nudge_telegram(overdue, now_ts=now_ts)
            # Pick the highest severity across the batch for the Alert header.
            severities = {item.escalated_severity(now_ts) for item in overdue}
            if "overdue" in severities:
                severity = "critical"
            elif "warning" in severities:
                severity = "warning"
            else:
                severity = "info"
            ctx.alerts.append(Alert(
                severity=severity,
                source=self.name,
                message=message,
                data={
                    "overdue_ids": [item.id for item in overdue],
                    "count": len(overdue),
                },
            ))
            for item in overdue:
                self._queue.mark_nudged(item.id, now_ts=now_ts)
                nudged_ids.append(item.id)
            log.info(
                "ActionQueue #%d: nudged %d overdue items (%s)",
                self._run_count,
                len(nudged_ids),
                ", ".join(nudged_ids),
            )
        elif overdue and ctx is None:
            # run_once called outside a tick (script / test); no ctx to alert
            # through, but we still want to update auto-fields and save.
            log.info(
                "ActionQueue #%d: %d overdue items but no ctx — not marking nudged",
                self._run_count, len(overdue),
            )
        else:
            log.info("ActionQueue #%d: nothing overdue", self._run_count)

        try:
            self._queue.save()
        except OSError as e:
            log.warning("ActionQueue: failed to save state: %s", e)

        return {
            "overdue_count": len(overdue),
            "nudged": nudged_ids,
            "total_items": len(self._queue.items),
        }

    # ── Auto-update ──────────────────────────────────────────

    def _auto_update_items(self, now_ts: float) -> None:
        """Update item fields by inspecting the system.

        Called before ``evaluate()`` so overdue decisions see fresh data.
        """
        # 1) lesson_approval_queue.context["pending_count"]
        pending = self._count_pending_lessons()
        if pending is not None:
            item = self._queue.get("lesson_approval_queue")
            if item is not None:
                ctx_payload = dict(item.context)
                ctx_payload["pending_count"] = int(pending)
                self._queue.set_context("lesson_approval_queue", ctx_payload)

        # 2) backup_health_check.last_done_ts from newest backup mtime.
        # The health check is considered "done" if a backup exists that's
        # < 2h old (matches the description text). This lets the
        # memory_backup iterator implicitly satisfy this check without
        # Chris having to manually mark it.
        newest_mtime = self._newest_backup_mtime()
        if newest_mtime is not None:
            age_s = now_ts - newest_mtime
            if age_s <= 2 * 3600:
                item = self._queue.get("backup_health_check")
                if item is not None and item.last_done_ts < newest_mtime:
                    self._queue.mark_done("backup_health_check", now_ts=newest_mtime)

    def _count_pending_lessons(self) -> Optional[int]:
        """Return the number of lessons with ``reviewed_by_chris == 0``.

        None on any error (missing DB, schema mismatch, locked, etc). The
        caller treats None as "don't update" rather than "zero".
        """
        if not self._memory_db_path.exists():
            return None
        try:
            conn = sqlite3.connect(f"file:{self._memory_db_path}?mode=ro", uri=True)
            try:
                row = conn.execute(
                    "SELECT COUNT(*) FROM lessons WHERE reviewed_by_chris = 0"
                ).fetchone()
            finally:
                conn.close()
        except sqlite3.DatabaseError as e:
            log.debug("ActionQueue: pending-lesson count failed: %s", e)
            return None
        if row is None:
            return None
        try:
            return int(row[0])
        except (TypeError, ValueError):
            return None

    def _newest_backup_mtime(self) -> Optional[float]:
        """Return the mtime of the newest file in the memory backup dir.

        None if the directory doesn't exist or is empty.
        """
        if not self._backup_dir.exists():
            return None
        try:
            entries = [
                p for p in self._backup_dir.iterdir()
                if p.is_file() and p.suffix == ".db"
            ]
        except OSError:
            return None
        if not entries:
            return None
        try:
            return max(p.stat().st_mtime for p in entries)
        except OSError:
            return None

    # ── Config ───────────────────────────────────────────────

    def _reload_config(self) -> None:
        if not self._config_path.exists():
            self._enabled = True  # default ON
            self._interval_s = DEFAULT_INTERVAL_HOURS * 3600
            return
        try:
            with self._config_path.open("r") as f:
                cfg = json.load(f)
        except (OSError, json.JSONDecodeError) as e:
            log.warning(
                "ActionQueue: bad config %s: %s — defaulting to enabled",
                self._config_path,
                e,
            )
            self._enabled = True
            return
        self._enabled = bool(cfg.get("enabled", True))
        try:
            self._interval_s = max(60, int(cfg.get("interval_hours", DEFAULT_INTERVAL_HOURS)) * 3600)
        except (TypeError, ValueError):
            self._interval_s = DEFAULT_INTERVAL_HOURS * 3600
