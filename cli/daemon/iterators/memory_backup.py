"""MemoryBackupIterator — periodic atomic snapshots of data/memory/memory.db.

Closes the SPOF flagged in the 2026-04-10 deep-dive review: the entire
lessons corpus + consolidated events + observations + action_log live in
ONE SQLite file with no backup, no replica, no transaction log shipped.
A single corrupt write, accidental delete, or schema migration mishap
loses everything.

This iterator runs inside the daemon clock and:

  1. Wakes every ``interval_hours`` hours (default 1h).
  2. Uses ``sqlite3.Connection.backup()`` — the proper online-backup API.
     This is safe with concurrent writers (the Telegram bot, dream cycle,
     lesson_author all hold connections to the same DB) because it copies
     pages under SQLite's own lock without taking the source DB offline.
  3. Writes the snapshot atomically: temp filename → fsync → rename.
  4. Runs ``PRAGMA integrity_check`` against the snapshot. A failed check
     does NOT delete the bad snapshot — it logs loud and keeps it for
     forensic recovery.
  5. Rotates retention: keeps the most recent N hourly + N daily + N
     weekly snapshots. Anything older is unlinked.

Pure stdlib. No external deps. No shell exec. No race with concurrent
writers. Read-only against the source DB so it's safe in every tier.

Kill switch: ``data/config/memory_backup.json`` → ``{"enabled": false}``.

Default config:
    {
      "enabled": true,
      "interval_hours": 1,
      "source_path": "data/memory/memory.db",
      "backup_dir": "data/memory/backups",
      "keep_hourly": 24,
      "keep_daily": 7,
      "keep_weekly": 4,
      "verify_integrity": true
    }

Output filenames are sortable and self-describing:
    memory-20260410-1400.db          ← hourly snapshot at 14:00 local
    memory-20260410-daily.db         ← rolled to "daily" slot at midnight
    memory-2026W15-weekly.db         ← rolled to "weekly" slot on Monday

Restore drill: see ``docs/wiki/operations/runbook.md``.
"""
from __future__ import annotations

import json
import logging
import sqlite3
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

log = logging.getLogger("iter.memory_backup")

DEFAULT_CONFIG_PATH = "data/config/memory_backup.json"
DEFAULT_SOURCE_PATH = "data/memory/memory.db"
DEFAULT_BACKUP_DIR = "data/memory/backups"
DEFAULT_INTERVAL_HOURS = 1
DEFAULT_KEEP_HOURLY = 24
DEFAULT_KEEP_DAILY = 7
DEFAULT_KEEP_WEEKLY = 4

# Filename prefixes — used by both write and rotation logic so they can
# never get out of sync.
HOURLY_PREFIX = "memory-"
HOURLY_SUFFIX = ".db"
DAILY_TAG = "-daily"
WEEKLY_TAG = "-weekly"


class MemoryBackupIterator:
    """Hourly atomic backup of memory.db with rotation + integrity check."""

    name = "memory_backup"

    def __init__(
        self,
        config_path: str = DEFAULT_CONFIG_PATH,
        source_path: Optional[str] = None,
        backup_dir: Optional[str] = None,
    ):
        self._config_path = Path(config_path)
        self._enabled: bool = True
        self._interval_s: int = DEFAULT_INTERVAL_HOURS * 3600
        self._source_path: Path = Path(source_path or DEFAULT_SOURCE_PATH)
        self._backup_dir: Path = Path(backup_dir or DEFAULT_BACKUP_DIR)
        self._keep_hourly: int = DEFAULT_KEEP_HOURLY
        self._keep_daily: int = DEFAULT_KEEP_DAILY
        self._keep_weekly: int = DEFAULT_KEEP_WEEKLY
        self._verify_integrity: bool = True
        self._last_run: float = 0
        self._run_count: int = 0

    # ── Lifecycle ────────────────────────────────────────────

    def on_start(self, ctx) -> None:
        self._reload_config()
        if not self._enabled:
            log.info("MemoryBackupIterator disabled via config — no-op")
            return
        self._backup_dir.mkdir(parents=True, exist_ok=True)
        log.info(
            "MemoryBackupIterator ready (interval=%ds, source=%s, dir=%s)",
            self._interval_s,
            self._source_path,
            self._backup_dir,
        )

    def tick(self, ctx) -> None:
        self._reload_config()
        if not self._enabled:
            return
        now = time.monotonic()
        if now - self._last_run < self._interval_s:
            return
        self._last_run = now
        self._run_count += 1

        try:
            self.run_once()
        except Exception as e:  # pragma: no cover — defensive only
            log.warning("MemoryBackup: tick failed: %s", e)

    def on_stop(self) -> None:
        log.info("MemoryBackupIterator stopped after %d runs", self._run_count)

    # ── Public single-shot entry point (for /memorybackup or scripts) ──

    def run_once(self) -> dict[str, Any]:
        """Take one snapshot + rotate. Returns a stats dict."""
        if not self._source_path.exists():
            log.warning(
                "MemoryBackup: source DB %s does not exist — skipping",
                self._source_path,
            )
            return {"skipped": True, "reason": "source_missing"}

        self._backup_dir.mkdir(parents=True, exist_ok=True)
        snapshot_path = self._snapshot_path_now()
        bytes_copied = self._atomic_backup(snapshot_path)

        integrity_ok = True
        if self._verify_integrity:
            integrity_ok = self._verify(snapshot_path)
            if not integrity_ok:
                log.error(
                    "MemoryBackup: integrity_check FAILED on %s — keeping "
                    "for forensic recovery, not rotating",
                    snapshot_path,
                )
                return {
                    "snapshot": str(snapshot_path),
                    "bytes": bytes_copied,
                    "integrity_ok": False,
                    "rotated": False,
                }

        # Promote to daily / weekly slots if appropriate
        promotions = self._maybe_promote(snapshot_path)
        # Drop anything past retention windows
        removed = self._rotate()

        log.info(
            "MemoryBackup #%d: wrote %s (%d bytes), promoted=%s, removed=%d old",
            self._run_count,
            snapshot_path.name,
            bytes_copied,
            promotions,
            removed,
        )
        return {
            "snapshot": str(snapshot_path),
            "bytes": bytes_copied,
            "integrity_ok": True,
            "promotions": promotions,
            "rotated_removed": removed,
        }

    # ── Config ───────────────────────────────────────────────

    def _reload_config(self) -> None:
        if not self._config_path.exists():
            self._enabled = True  # default ON
            return
        try:
            with self._config_path.open("r") as f:
                cfg = json.load(f)
        except (OSError, json.JSONDecodeError) as e:
            log.warning(
                "MemoryBackup: bad config %s: %s — defaulting to enabled",
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
        if cfg.get("source_path"):
            self._source_path = Path(cfg["source_path"])
        if cfg.get("backup_dir"):
            self._backup_dir = Path(cfg["backup_dir"])
        try:
            self._keep_hourly = max(1, int(cfg.get("keep_hourly", DEFAULT_KEEP_HOURLY)))
            self._keep_daily = max(1, int(cfg.get("keep_daily", DEFAULT_KEEP_DAILY)))
            self._keep_weekly = max(1, int(cfg.get("keep_weekly", DEFAULT_KEEP_WEEKLY)))
        except (TypeError, ValueError):
            pass
        self._verify_integrity = bool(cfg.get("verify_integrity", True))

    # ── Snapshot path naming ─────────────────────────────────

    def _snapshot_path_now(self) -> Path:
        ts = datetime.now().strftime("%Y%m%d-%H%M")
        return self._backup_dir / f"{HOURLY_PREFIX}{ts}{HOURLY_SUFFIX}"

    # ── Atomic backup ────────────────────────────────────────

    def _atomic_backup(self, dest: Path) -> int:
        """Run sqlite3 online-backup into a .tmp file, fsync, rename.

        Returns: bytes written (snapshot size on disk).
        """
        tmp = dest.with_suffix(dest.suffix + ".tmp")
        if tmp.exists():
            tmp.unlink()
        src_conn = sqlite3.connect(f"file:{self._source_path}?mode=ro", uri=True)
        dst_conn = sqlite3.connect(str(tmp))
        try:
            with dst_conn:
                src_conn.backup(dst_conn)
        finally:
            src_conn.close()
            dst_conn.close()
        # fsync + rename
        try:
            with tmp.open("rb") as fh:
                import os
                os.fsync(fh.fileno())
        except OSError:
            pass
        tmp.replace(dest)
        return dest.stat().st_size

    # ── Integrity verify ─────────────────────────────────────

    def _verify(self, snapshot: Path) -> bool:
        try:
            conn = sqlite3.connect(f"file:{snapshot}?mode=ro", uri=True)
            try:
                row = conn.execute("PRAGMA integrity_check").fetchone()
            finally:
                conn.close()
        except sqlite3.DatabaseError as e:
            log.warning("MemoryBackup: integrity_check raised on %s: %s", snapshot, e)
            return False
        return bool(row) and row[0] == "ok"

    # ── Promotion to daily / weekly slots ────────────────────

    def _maybe_promote(self, snapshot: Path) -> dict[str, bool]:
        """If this snapshot is the first of its day/week, copy it to
        the daily/weekly slot. Idempotent — re-running on the same hour
        will overwrite the slot file with the latest snapshot only if
        no slot file for today/this-week exists yet.
        """
        import shutil

        promotions = {"daily": False, "weekly": False}
        now = datetime.now()
        # Daily slot — one per YYYYMMDD
        daily_path = self._backup_dir / f"{HOURLY_PREFIX}{now.strftime('%Y%m%d')}{DAILY_TAG}{HOURLY_SUFFIX}"
        if not daily_path.exists():
            try:
                shutil.copy2(snapshot, daily_path)
                promotions["daily"] = True
            except OSError as e:
                log.warning("MemoryBackup: daily promotion failed: %s", e)

        # Weekly slot — one per ISO year-week
        iso_year, iso_week, _ = now.isocalendar()
        weekly_path = self._backup_dir / f"{HOURLY_PREFIX}{iso_year}W{iso_week:02d}{WEEKLY_TAG}{HOURLY_SUFFIX}"
        if not weekly_path.exists():
            try:
                shutil.copy2(snapshot, weekly_path)
                promotions["weekly"] = True
            except OSError as e:
                log.warning("MemoryBackup: weekly promotion failed: %s", e)

        return promotions

    # ── Rotation ─────────────────────────────────────────────

    def _rotate(self) -> int:
        """Drop snapshots past their retention window. Returns count removed."""
        removed = 0
        all_files = sorted(self._backup_dir.glob(f"{HOURLY_PREFIX}*{HOURLY_SUFFIX}"))

        hourly = [p for p in all_files if DAILY_TAG not in p.name and WEEKLY_TAG not in p.name]
        daily = [p for p in all_files if DAILY_TAG in p.name]
        weekly = [p for p in all_files if WEEKLY_TAG in p.name]

        for keep, group in (
            (self._keep_hourly, hourly),
            (self._keep_daily, daily),
            (self._keep_weekly, weekly),
        ):
            if len(group) > keep:
                for old in group[: len(group) - keep]:
                    try:
                        old.unlink()
                        removed += 1
                    except OSError as e:
                        log.warning("MemoryBackup: failed to unlink %s: %s", old, e)
        return removed
