"""File-based state reader with modification-time caching."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from web.api.readers.base import StateReader


class FileStateReader(StateReader):
    """Reads JSON state files with stat-based caching."""

    def __init__(self, data_dir: Path, state_dir: Path | None = None):
        self._data_dir = data_dir
        self._state_dir = state_dir or data_dir.parent / "state"
        self._cache: dict[str, tuple[float, dict]] = {}

    def _resolve_path(self, key: str) -> Path:
        """Map logical key to file path."""
        mapping = {
            "daemon_state": self._data_dir / "daemon" / "state.json",
            "telemetry": self._state_dir / "telemetry.json",
            "working_state": self._data_dir / "memory" / "working_state.json",
        }
        if key in mapping:
            return mapping[key]
        # Fallback: treat as relative path under data_dir
        return self._data_dir / key

    def read(self, key: str) -> dict[str, Any]:
        path = self._resolve_path(key)
        if not path.exists():
            return {}

        mtime = os.path.getmtime(path)
        cached = self._cache.get(key)
        if cached and cached[0] == mtime:
            return cached[1]

        try:
            data = json.loads(path.read_text())
        except (json.JSONDecodeError, OSError):
            return {}

        self._cache[key] = (mtime, data)
        return data

    def write(self, key: str, data: dict[str, Any]) -> None:
        path = self._resolve_path(key)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2))
        tmp.replace(path)
        # Invalidate cache
        self._cache.pop(key, None)
