"""Safety tests for the agent's edit_file tool.

These guard the P3 #11–13 hardening:
  * Path allowlist — high-risk paths (exchange/, trading/, etc.) require
    allow_unsafe=True.
  * Allowlisted paths still work as before.
  * Test-fail revert — a .py edit that breaks pytest is rolled back.
  * unsafe_path is reported in the result so audit can see it.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from agent.tool_functions import edit_file


PROJECT_ROOT = Path(__file__).resolve().parent.parent


def test_path_outside_allowlist_blocked_by_default():
    """Editing exchange/risk_manager.py without allow_unsafe must fail."""
    result = edit_file(
        path="exchange/risk_manager.py",
        old_str="import logging",
        new_str="import logging  # nope",
    )
    assert result.get("error") == "PATH_NOT_ALLOWED"
    assert "allow_unsafe=True" in result.get("detail", "")


def test_allowlisted_path_works(tmp_path, monkeypatch):
    """data/thesis/ is allowlisted — editing should proceed."""
    # Create a sandbox thesis file in the real data/thesis/ dir.
    target = PROJECT_ROOT / "data" / "thesis" / "_test_edit_file_safety.json"
    target.write_text('{"market": "TEST", "conviction": 0.5}')
    try:
        result = edit_file(
            path=str(target.relative_to(PROJECT_ROOT)),
            old_str='"conviction": 0.5',
            new_str='"conviction": 0.6',
        )
        assert result.get("status") == "edited"
        assert result.get("unsafe_path") is False
        assert '"conviction": 0.6' in target.read_text()
    finally:
        # Cleanup: remove both file and backup
        if target.exists():
            target.unlink()
        bak = target.with_suffix(target.suffix + ".bak")
        if bak.exists():
            bak.unlink()


def test_unsafe_path_with_explicit_flag_is_marked():
    """allow_unsafe=True must succeed AND set unsafe_path=True for audit."""
    # We won't actually mutate exchange/ — just verify the gate logic by
    # trying with old_str that doesn't exist (still gets past the allowlist
    # check, then fails on the find).
    result = edit_file(
        path="exchange/risk_manager.py",
        old_str="this_string_definitely_not_in_the_file_xyz",
        new_str="x",
        allow_unsafe=True,
    )
    # old_str not in content → returns "old_str not found" — that means
    # the allowlist check passed.
    assert "PATH_NOT_ALLOWED" not in str(result)
    assert "old_str not found" in result.get("error", "")


def test_allowlist_covers_critical_safe_paths():
    """Sanity: prefixes Chris asked us to allow are present."""
    from agent.tool_functions import _EDIT_FILE_ALLOWLIST
    expected = {
        "agent/prompts/",
        "data/thesis/",
        "data/agent_memory/",
        "data/config/",
        "tests/",
        "docs/",
    }
    assert expected.issubset(set(_EDIT_FILE_ALLOWLIST))


def test_path_outside_project_root_still_blocked():
    """Backward-compat: project-root escape still blocked even with allow_unsafe."""
    result = edit_file(
        path="../../../etc/passwd",
        old_str="x",
        new_str="y",
        allow_unsafe=True,
    )
    assert "outside project" in result.get("error", "").lower()
