"""Trajectory — JSONL session logger for daemon and heartbeat runs.

Inspired by ByteDance Trae Agent's trajectory recording. Every significant
action is appended to a session-specific JSONL file for trivial debugging:
just `cat` the file to see exactly what happened.

Files are written to:  logs/trajectory_YYYYMMDD_HHMMSS_{component}.jsonl
"""
from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

log = logging.getLogger("trajectory")

# Default directory for trajectory files
DEFAULT_LOG_DIR = Path(__file__).resolve().parent.parent / "logs" / "trajectories"


@dataclass
class TrajectoryEntry:
    """A single entry in the trajectory log."""
    ts: float
    component: str       # "heartbeat", "daemon", "event_watcher"
    action: str          # "stop_placed", "dip_detected", "tick_complete", etc.
    symbol: Optional[str] = None
    details: Optional[Dict[str, Any]] = None
    status: Optional[str] = None  # "ok", "error", "skipped"

    def to_json(self) -> str:
        d = {k: v for k, v in asdict(self).items() if v is not None}
        return json.dumps(d, default=str)


class TrajectoryLogger:
    """Appends structured JSONL entries to a session-specific log file.

    Usage:
        traj = TrajectoryLogger("heartbeat")
        traj.log("stop_placed", symbol="BRENTOIL", details={"price": 108.5})
        traj.log("tick_complete", details={"positions_checked": 3})
        traj.close()
    """

    RETENTION_DAYS = 7

    def __init__(self, component: str, log_dir: Optional[Path] = None):
        self.component = component
        self.log_dir = Path(log_dir) if log_dir else DEFAULT_LOG_DIR
        self.log_dir.mkdir(parents=True, exist_ok=True)

        self._purge_old()

        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.filepath = self.log_dir / f"trajectory_{ts}_{component}.jsonl"
        self._file = open(self.filepath, "a", buffering=1)  # line-buffered
        self._entry_count = 0
        log.info("Trajectory logger started: %s", self.filepath)

    def _purge_old(self) -> None:
        """Delete trajectory files older than RETENTION_DAYS."""
        cutoff = time.time() - self.RETENTION_DAYS * 86400
        removed = 0
        for f in self.log_dir.glob("trajectory_*.jsonl"):
            try:
                if f.stat().st_mtime < cutoff:
                    f.unlink()
                    removed += 1
            except OSError:
                pass
        if removed:
            log.info("Trajectory retention: removed %d files older than %d days", removed, self.RETENTION_DAYS)

    def log(
        self,
        action: str,
        symbol: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
        status: str = "ok",
    ) -> None:
        """Append an entry to the trajectory log."""
        entry = TrajectoryEntry(
            ts=time.time(),
            component=self.component,
            action=action,
            symbol=symbol,
            details=details,
            status=status,
        )
        try:
            self._file.write(entry.to_json() + "\n")
            self._entry_count += 1
        except Exception as e:
            log.warning("Failed to write trajectory entry: %s", e)

    def close(self) -> None:
        """Close the trajectory file."""
        try:
            self._file.close()
            log.info("Trajectory closed: %s (%d entries)", self.filepath, self._entry_count)
        except Exception:
            pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    @property
    def entry_count(self) -> int:
        return self._entry_count
