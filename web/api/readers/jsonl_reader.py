"""Paginated JSONL file reader."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from web.api.readers.base import EventReader


class FileEventReader(EventReader):
    """Reads JSONL files with pagination, newest-first."""

    def __init__(self, path: Path):
        self._path = path

    def _read_all(self) -> list[dict[str, Any]]:
        if not self._path.exists():
            return []
        lines = []
        try:
            with open(self._path, "r") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        try:
                            lines.append(json.loads(line))
                        except json.JSONDecodeError:
                            continue
        except OSError:
            return []
        return lines

    def read_latest(self, limit: int = 50) -> list[dict[str, Any]]:
        all_entries = self._read_all()
        # Return newest first
        return list(reversed(all_entries[-limit:]))

    def read_range(self, start: datetime, end: datetime) -> list[dict[str, Any]]:
        all_entries = self._read_all()
        start_ts = start.timestamp() * 1000  # unix ms
        end_ts = end.timestamp() * 1000
        filtered = []
        for entry in all_entries:
            ts = entry.get("timestamp") or entry.get("timestamp_ms") or entry.get("ts", 0)
            if isinstance(ts, str):
                continue  # Skip ISO timestamps for now
            if start_ts <= ts <= end_ts:
                filtered.append(entry)
        return list(reversed(filtered))
