"""Diagnostics system — tracks MCP tool calls, chat interactions, and errors.

Provides visibility into what OpenClaw is doing, what's failing, and why.
All logs go to data/diagnostics/ as rotated JSONL files.

Usage:
    from common.diagnostics import diag

    diag.log_tool_call("account", args={}, result="...", duration_ms=42)
    diag.log_chat("user", "How's my oil position?")
    diag.log_chat("agent", "BRENTOIL is long 20 @ 107.5...")
    diag.log_error("mcp", "Tool 'status' timed out after 30s")
"""
from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

log = logging.getLogger("diagnostics")

_DIAG_DIR = Path("data/diagnostics")
_MAX_LOG_BYTES = 500_000  # 500KB per log file before rotation
_MAX_LOG_FILES = 5        # keep last 5 rotated files


@dataclass
class DiagEntry:
    """Single diagnostic event."""
    timestamp: str
    timestamp_ms: int
    category: str       # "tool_call", "chat", "error", "startup", "health"
    event: str          # specific event name
    data: Dict[str, Any] = field(default_factory=dict)
    duration_ms: Optional[int] = None

    def to_dict(self) -> dict:
        d = {
            "ts": self.timestamp,
            "ts_ms": self.timestamp_ms,
            "cat": self.category,
            "event": self.event,
        }
        if self.duration_ms is not None:
            d["dur_ms"] = self.duration_ms
        if self.data:
            d["data"] = self.data
        return d


class DiagnosticsLogger:
    """Append-only JSONL logger for diagnostics."""

    def __init__(self, diag_dir: str | Path = _DIAG_DIR):
        self.diag_dir = Path(diag_dir)
        self.diag_dir.mkdir(parents=True, exist_ok=True)
        self._tool_log = self.diag_dir / "tool_calls.jsonl"
        self._chat_log = self.diag_dir / "chat_log.jsonl"
        self._error_log = self.diag_dir / "errors.jsonl"
        self._health_log = self.diag_dir / "health.jsonl"

        # In-memory counters for quick health checks
        self._tool_counts: Dict[str, int] = {}
        self._error_counts: Dict[str, int] = {}
        self._session_start = int(time.time() * 1000)

    def _now(self) -> tuple[str, int]:
        now = datetime.now(timezone.utc)
        return now.strftime("%Y-%m-%d %H:%M:%S"), int(now.timestamp() * 1000)

    def _append(self, path: Path, entry: DiagEntry) -> None:
        """Append entry to JSONL file with rotation."""
        try:
            self._rotate_if_needed(path)
            with open(path, "a") as f:
                f.write(json.dumps(entry.to_dict(), separators=(",", ":")) + "\n")
        except Exception as e:
            log.warning("Diag write failed (%s): %s", path.name, e)

    def _rotate_if_needed(self, path: Path) -> None:
        """Rotate log if it exceeds max size."""
        if not path.exists():
            return
        try:
            if path.stat().st_size < _MAX_LOG_BYTES:
                return
        except OSError:
            return

        # Rotate: .jsonl → .1.jsonl → .2.jsonl → ... → delete oldest
        stem = path.stem
        suffix = path.suffix
        for i in range(_MAX_LOG_FILES, 0, -1):
            old = path.parent / f"{stem}.{i}{suffix}"
            new = path.parent / f"{stem}.{i + 1}{suffix}"
            if old.exists():
                if i >= _MAX_LOG_FILES:
                    old.unlink()
                else:
                    old.rename(new)
        path.rename(path.parent / f"{stem}.1{suffix}")

    # ── Public API ──────────────────────────────────────────────

    def log_tool_call(
        self,
        tool_name: str,
        args: Optional[Dict] = None,
        result: Optional[str] = None,
        duration_ms: Optional[int] = None,
        error: Optional[str] = None,
    ) -> None:
        """Log an MCP tool call (success or failure)."""
        ts, ts_ms = self._now()
        self._tool_counts[tool_name] = self._tool_counts.get(tool_name, 0) + 1

        data: Dict[str, Any] = {"tool": tool_name}
        if args:
            data["args"] = args
        if result:
            # Truncate large results
            data["result"] = result[:500] if len(result) > 500 else result
        if error:
            data["error"] = error
            self._error_counts[tool_name] = self._error_counts.get(tool_name, 0) + 1

        entry = DiagEntry(
            timestamp=ts, timestamp_ms=ts_ms,
            category="tool_call",
            event=f"{'error' if error else 'ok'}:{tool_name}",
            data=data, duration_ms=duration_ms,
        )
        self._append(self._tool_log, entry)

        if error:
            self._append(self._error_log, entry)
            log.warning("Tool call failed: %s — %s", tool_name, error)

    def log_chat(
        self,
        role: str,  # "user" or "agent"
        text: str,
        channel: str = "telegram",
        metadata: Optional[Dict] = None,
    ) -> None:
        """Log a chat message (user or agent)."""
        ts, ts_ms = self._now()
        data: Dict[str, Any] = {
            "role": role,
            "channel": channel,
            "text": text[:2000],  # cap at 2000 chars
        }
        if metadata:
            data["meta"] = metadata

        entry = DiagEntry(
            timestamp=ts, timestamp_ms=ts_ms,
            category="chat", event=f"{role}:{channel}",
            data=data,
        )
        self._append(self._chat_log, entry)

    def log_error(
        self,
        source: str,
        message: str,
        details: Optional[Dict] = None,
    ) -> None:
        """Log an error from any subsystem."""
        ts, ts_ms = self._now()
        self._error_counts[source] = self._error_counts.get(source, 0) + 1

        data: Dict[str, Any] = {"source": source, "message": message}
        if details:
            data["details"] = details

        entry = DiagEntry(
            timestamp=ts, timestamp_ms=ts_ms,
            category="error", event=f"error:{source}",
            data=data,
        )
        self._append(self._error_log, entry)
        log.error("[%s] %s", source, message)

    def log_health(self, component: str, status: str, details: Optional[Dict] = None) -> None:
        """Log a health check result."""
        ts, ts_ms = self._now()
        data: Dict[str, Any] = {"component": component, "status": status}
        if details:
            data.update(details)

        entry = DiagEntry(
            timestamp=ts, timestamp_ms=ts_ms,
            category="health", event=f"health:{component}",
            data=data,
        )
        self._append(self._health_log, entry)

    def get_summary(self) -> Dict[str, Any]:
        """Quick diagnostic summary for /diag command."""
        uptime_ms = int(time.time() * 1000) - self._session_start
        return {
            "uptime_seconds": uptime_ms // 1000,
            "tool_calls": dict(self._tool_counts),
            "total_tool_calls": sum(self._tool_counts.values()),
            "errors": dict(self._error_counts),
            "total_errors": sum(self._error_counts.values()),
            "log_files": {
                "tool_calls": str(self._tool_log),
                "chat": str(self._chat_log),
                "errors": str(self._error_log),
            },
        }

    def get_recent_errors(self, limit: int = 10) -> List[Dict]:
        """Read recent errors from the log file."""
        if not self._error_log.exists():
            return []
        try:
            lines = self._error_log.read_text().splitlines()
            recent = lines[-limit:] if len(lines) > limit else lines
            return [json.loads(line) for line in recent if line.strip()]
        except Exception:
            return []

    def get_recent_chats(self, limit: int = 20) -> List[Dict]:
        """Read recent chat messages from the log file."""
        if not self._chat_log.exists():
            return []
        try:
            lines = self._chat_log.read_text().splitlines()
            recent = lines[-limit:] if len(lines) > limit else lines
            return [json.loads(line) for line in recent if line.strip()]
        except Exception:
            return []


# Singleton instance
diag = DiagnosticsLogger()
