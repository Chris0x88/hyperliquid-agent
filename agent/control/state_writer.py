"""Atomic JSON write helper for data/agent/state.json.

Uses the tempfile + os.replace pattern so the state file is always
parseable JSON — never a partial write even mid-crash.
"""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

_DEFAULT_STATE_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "agent" / "state.json"


def atomic_write_json(data: dict, path: Path | str | None = None) -> None:
    """Write `data` as JSON to `path` atomically.

    Creates parent directories if they don't exist.
    Writes to a sibling .tmp file then renames — guarantees the live file
    is never a partial write.
    """
    target = Path(path) if path is not None else _DEFAULT_STATE_PATH
    target.parent.mkdir(parents=True, exist_ok=True)

    # Write to a sibling tmp file in the same directory so rename is atomic
    # (same filesystem — avoids cross-device rename on macOS /tmp vs project vol)
    fd, tmp_path = tempfile.mkstemp(
        dir=target.parent,
        prefix=".state_tmp_",
        suffix=".json",
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, default=str)
            f.write("\n")
        os.replace(tmp_path, target)
    except Exception:
        # Clean up tmp on any failure — don't leave orphans
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def read_state_json(path: Path | str | None = None) -> dict:
    """Read and parse the state JSON file.  Returns empty dict on missing/corrupt."""
    target = Path(path) if path is not None else _DEFAULT_STATE_PATH
    try:
        with open(target, encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}
