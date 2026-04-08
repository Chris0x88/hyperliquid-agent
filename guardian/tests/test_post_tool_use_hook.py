"""Tests for the PostToolUse Read hook."""
from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest


HOOK_PATH = Path(__file__).parent.parent / "hooks" / "post_tool_use.py"


def _load_hook():
    spec = importlib.util.spec_from_file_location("guardian_post_tool_use_hook", HOOK_PATH)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _run_hook(stdin_json: str) -> tuple[int, str]:
    """Run the hook script as a subprocess with the given stdin payload."""
    proc = subprocess.run(
        [sys.executable, str(HOOK_PATH)],
        input=stdin_json,
        capture_output=True,
        text=True,
    )
    return proc.returncode, proc.stdout


def test_hook_exits_cleanly_on_empty_stdin():
    code, _ = _run_hook("")
    assert code == 0


def test_hook_exits_cleanly_on_malformed_json():
    code, _ = _run_hook("not json at all")
    assert code == 0


def test_hook_ignores_non_read_tools():
    from guardian.gate import reset_session_reads, _SESSION_READS_FILE
    reset_session_reads()
    code, _ = _run_hook(json.dumps({
        "tool_name": "Bash",
        "tool_input": {"command": "ls"},
    }))
    assert code == 0
    # No file should have been marked read
    assert not _SESSION_READS_FILE.exists() or _SESSION_READS_FILE.read_text().strip() == ""


def test_hook_marks_read_file(tmp_path: Path):
    from guardian.gate import reset_session_reads, _has_been_read
    reset_session_reads()
    target = tmp_path / "MASTER_PLAN.md"
    target.write_text("x")
    code, _ = _run_hook(json.dumps({
        "tool_name": "Read",
        "tool_input": {"file_path": str(target)},
    }))
    assert code == 0
    assert _has_been_read("MASTER_PLAN.md")


def test_hook_handles_missing_file_path():
    from guardian.gate import reset_session_reads
    reset_session_reads()
    code, _ = _run_hook(json.dumps({
        "tool_name": "Read",
        "tool_input": {},
    }))
    assert code == 0  # Should not crash even without file_path


def test_hook_handles_toolName_camelcase():
    """The hook tolerates both snake_case and camelCase field names."""
    from guardian.gate import reset_session_reads, _has_been_read
    reset_session_reads()
    import tempfile
    with tempfile.NamedTemporaryFile(suffix="_AUDIT_FIX_PLAN.md", delete=False) as f:
        f.write(b"x")
        path = f.name
    try:
        code, _ = _run_hook(json.dumps({
            "toolName": "Read",
            "toolInput": {"file_path": path},
        }))
        assert code == 0
        assert _has_been_read("AUDIT_FIX_PLAN.md")
    finally:
        os.unlink(path)
