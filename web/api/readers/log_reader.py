"""Log file reader with tail and streaming support."""

from __future__ import annotations

import asyncio
import os
import re
from pathlib import Path
from typing import AsyncIterator


# Log level patterns for colour coding
_LEVEL_RE = re.compile(r"\b(ERROR|WARNING|WARN|INFO|DEBUG|CRITICAL)\b")


def _detect_level(line: str) -> str:
    m = _LEVEL_RE.search(line)
    return m.group(1).lower() if m else "info"


class LogReader:
    """Reads log files and provides tail/stream functionality."""

    # Known log sources and their paths (relative to data_dir)
    SOURCES = {
        "daemon": "daemon/daemon.log",
        "daemon_err": "daemon/daemon_launchd_err.log",
        "heartbeat": "memory/logs/heartbeat_launchd.log",
        "telegram": "daemon/telegram_bot.log",
    }

    def __init__(self, data_dir: Path, logs_dir: Path | None = None):
        self._data_dir = data_dir
        self._logs_dir = logs_dir or data_dir.parent / "logs"

    def available_sources(self) -> list[dict]:
        sources = []
        for name, rel_path in self.SOURCES.items():
            path = self._data_dir / rel_path
            if path.exists():
                sources.append({
                    "name": name,
                    "path": str(path),
                    "size_bytes": path.stat().st_size,
                })
        # Also check logs/ directory
        if self._logs_dir.exists():
            for f in self._logs_dir.glob("*.log"):
                sources.append({
                    "name": f.stem,
                    "path": str(f),
                    "size_bytes": f.stat().st_size,
                })
        return sources

    def _resolve_source(self, source: str) -> Path | None:
        if source in self.SOURCES:
            path = self._data_dir / self.SOURCES[source]
            return path if path.exists() else None
        # Check logs/ dir
        path = self._logs_dir / f"{source}.log"
        return path if path.exists() else None

    def tail(self, source: str, lines: int = 100) -> list[dict]:
        """Return the last N lines from a log source."""
        path = self._resolve_source(source)
        if not path:
            return []

        try:
            with open(path, "rb") as f:
                # Seek to end and read backwards
                f.seek(0, 2)
                size = f.tell()
                if size == 0:
                    return []

                # Read last chunk (estimate ~200 bytes/line)
                chunk_size = min(size, lines * 200)
                f.seek(max(0, size - chunk_size))
                text = f.read().decode("utf-8", errors="replace")

            raw_lines = text.splitlines()[-lines:]
            return [
                {"text": line, "level": _detect_level(line)}
                for line in raw_lines
                if line.strip()
            ]
        except OSError:
            return []

    async def stream(self, source: str) -> AsyncIterator[dict]:
        """Async generator that yields new log lines as they appear."""
        path = self._resolve_source(source)
        if not path:
            return

        try:
            size = os.path.getsize(path)
        except OSError:
            return

        while True:
            await asyncio.sleep(1)
            try:
                new_size = os.path.getsize(path)
            except OSError:
                continue

            if new_size > size:
                try:
                    with open(path, "rb") as f:
                        f.seek(size)
                        new_data = f.read(new_size - size)
                    size = new_size
                    for line in new_data.decode("utf-8", errors="replace").splitlines():
                        if line.strip():
                            yield {"text": line, "level": _detect_level(line), "source": source}
                except OSError:
                    continue
            elif new_size < size:
                # File was truncated (log rotation)
                size = new_size
