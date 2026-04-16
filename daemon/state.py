"""Daemon state persistence and control file handling.

All writes use atomic rename (write to .tmp, then replace) so a crash
mid-write cannot corrupt the state file.
"""
from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

log = logging.getLogger("daemon.state")


@dataclass
class DaemonState:
    """Persisted daemon state — survives restarts."""
    tier: str = "watch"
    tick_count: int = 0
    daily_pnl: float = 0.0
    total_pnl: float = 0.0
    total_trades: int = 0

    def to_dict(self) -> dict:
        return {
            "tier": self.tier,
            "tick_count": self.tick_count,
            "daily_pnl": self.daily_pnl,
            "total_pnl": self.total_pnl,
            "total_trades": self.total_trades,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "DaemonState":
        return cls(**{k: d[k] for k in cls.__dataclass_fields__ if k in d})


class StateStore:
    """Single persistence layer for daemon state."""

    def __init__(self, data_dir: str = "data/daemon"):
        self._dir = Path(data_dir)
        self._state_path = self._dir / "state.json"
        self._control_path = self._dir / "control.json"
        self._pid_path = self._dir / "daemon.pid"

    def ensure_dir(self) -> None:
        self._dir.mkdir(parents=True, exist_ok=True)

    # ── State ────────────────────────────────────────────────

    def save_state(self, state: DaemonState) -> None:
        self.ensure_dir()
        self._atomic_write(self._state_path, json.dumps(state.to_dict(), indent=2))

    def load_state(self) -> DaemonState:
        if self._state_path.exists():
            return DaemonState.from_dict(json.loads(self._state_path.read_text()))
        return DaemonState()

    # ── PID ──────────────────────────────────────────────────

    def write_pid(self) -> None:
        self.ensure_dir()
        self._atomic_write(self._pid_path, str(os.getpid()))

    def remove_pid(self) -> None:
        self._pid_path.unlink(missing_ok=True)

    def read_pid(self) -> Optional[int]:
        if self._pid_path.exists():
            try:
                return int(self._pid_path.read_text().strip())
            except ValueError:
                return None
        return None

    def is_running(self) -> bool:
        pid = self.read_pid()
        if pid is None:
            return False
        try:
            os.kill(pid, 0)
            return True
        except OSError:
            return False

    # ── Control file (IPC) ───────────────────────────────────

    def read_control(self) -> Optional[Dict[str, Any]]:
        """Read and clear the control file. Returns None if no command pending."""
        if not self._control_path.exists():
            return None
        try:
            data = json.loads(self._control_path.read_text())
            self._control_path.unlink()
            return data
        except (json.JSONDecodeError, OSError):
            self._control_path.unlink(missing_ok=True)
            return None

    def write_control(self, command: Dict[str, Any]) -> None:
        """Write a control command for the running daemon to pick up."""
        self.ensure_dir()
        self._atomic_write(self._control_path, json.dumps(command))

    # ── Helpers ──────────────────────────────────────────────

    @staticmethod
    def _atomic_write(path: Path, content: str) -> None:
        """Write content to path atomically via tmp+rename."""
        tmp = path.with_suffix(".tmp")
        tmp.write_text(content)
        tmp.replace(path)
