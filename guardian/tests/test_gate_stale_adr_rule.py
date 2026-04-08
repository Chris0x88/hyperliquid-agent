"""Tests for the stale-adr-guard gate rule."""
from __future__ import annotations

from pathlib import Path

from guardian.gate import check_tool_use, mark_file_read, reset_session_reads


def test_rule_allows_adr_edit_after_required_reads(tmp_path: Path, monkeypatch):
    reset_session_reads()
    adr_dir = tmp_path / "docs" / "wiki" / "decisions"
    adr_dir.mkdir(parents=True)
    adr_file = adr_dir / "015-new.md"
    plans_dir = tmp_path / "docs" / "plans"
    plans_dir.mkdir(parents=True)
    master = plans_dir / "MASTER_PLAN.md"
    audit = plans_dir / "AUDIT_FIX_PLAN.md"
    master.write_text("x")
    audit.write_text("x")

    mark_file_read(str(master))
    mark_file_read(str(audit))

    result = check_tool_use(
        tool_name="Write",
        tool_input={"file_path": str(adr_file), "content": "# ADR-015"},
    )
    assert result.allow is True


def test_rule_blocks_adr_without_reading_master_plan(tmp_path: Path, monkeypatch):
    reset_session_reads()
    adr_dir = tmp_path / "docs" / "wiki" / "decisions"
    adr_dir.mkdir(parents=True)
    adr_file = adr_dir / "016-new.md"
    plans_dir = tmp_path / "docs" / "plans"
    plans_dir.mkdir(parents=True)
    (plans_dir / "MASTER_PLAN.md").write_text("x")
    (plans_dir / "AUDIT_FIX_PLAN.md").write_text("x")

    # Only mark AUDIT_FIX_PLAN as read — not MASTER_PLAN
    mark_file_read(str(plans_dir / "AUDIT_FIX_PLAN.md"))

    result = check_tool_use(
        tool_name="Write",
        tool_input={"file_path": str(adr_file), "content": "# ADR-016"},
    )
    assert result.allow is False
    assert "MASTER_PLAN" in (result.reason or "")
    assert result.rule == "stale-adr-guard"


def test_rule_kill_switch(tmp_path: Path, monkeypatch):
    reset_session_reads()
    monkeypatch.setenv("GUARDIAN_RULE_STALE_ADR", "0")
    adr_file = tmp_path / "docs" / "wiki" / "decisions" / "017-new.md"
    adr_file.parent.mkdir(parents=True)
    result = check_tool_use(
        tool_name="Write",
        tool_input={"file_path": str(adr_file), "content": "# ADR-017"},
    )
    assert result.allow is True


def test_rule_ignores_non_adr_files(tmp_path: Path, monkeypatch):
    reset_session_reads()
    other = tmp_path / "some_file.py"
    result = check_tool_use(
        tool_name="Write",
        tool_input={"file_path": str(other), "content": "x"},
    )
    assert result.allow is True
