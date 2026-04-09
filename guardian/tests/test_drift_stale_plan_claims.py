"""Tests for drift.detect_stale_plan_claims().

The classic failure mode this catches: MASTER_PLAN.md says
"Not yet wired: cli/daemon/iterators/lesson_author.py" but the file
is in the inventory and registered in tiers.py — meaning the plan is
stale and should be archived + rewritten.
"""
from __future__ import annotations

from pathlib import Path

from guardian.drift import detect_stale_plan_claims


def _inventory_with(*paths: str) -> dict:
    return {
        "modules": [{"name": p.replace("/", ".").rstrip(".py"), "path": p} for p in paths],
        "edges": [],
    }


def test_no_findings_when_plan_is_clean(tmp_path: Path):
    plan = tmp_path / "MASTER_PLAN.md"
    plan.write_text("# Plan\n\nAll subsystems shipped.\n")
    inv = _inventory_with("cli/daemon/iterators/lesson_author.py")
    assert detect_stale_plan_claims(plan, inv) == []


def test_no_findings_when_plan_missing(tmp_path: Path):
    plan = tmp_path / "missing.md"
    inv = _inventory_with("a.py")
    assert detect_stale_plan_claims(plan, inv) == []


def test_stale_claim_when_plan_says_not_wired_but_file_exists(tmp_path: Path):
    plan = tmp_path / "MASTER_PLAN.md"
    plan.write_text(
        "# Plan\n\n"
        "**Not yet wired:** `cli/daemon/iterators/lesson_author.py`, "
        "`cli/agent_tools.py` updates.\n"
    )
    inv = _inventory_with(
        "cli/daemon/iterators/lesson_author.py",
        "cli/agent_tools.py",
    )
    findings = detect_stale_plan_claims(plan, inv)
    assert len(findings) == 1  # one finding per sentinel hit
    assert findings[0]["severity"] == "P1"
    assert "lesson_author.py" in findings[0]["stale_reference"]


def test_stale_claim_when_plan_says_wiring_deferred(tmp_path: Path):
    plan = tmp_path / "MASTER_PLAN.md"
    plan.write_text(
        "Trade lesson layer — data layer SHIPPED, wiring deferred:\n"
        "- `modules/lesson_engine.py`\n"
    )
    inv = _inventory_with("modules/lesson_engine.py")
    findings = detect_stale_plan_claims(plan, inv)
    assert len(findings) == 1
    assert "deferred" in findings[0]["claim"].lower()


def test_stale_claim_when_plan_says_empty_shell(tmp_path: Path):
    plan = tmp_path / "MASTER_PLAN.md"
    plan.write_text(
        "Lesson table is an empty shell until `cli/daemon/iterators/lesson_author.py` ships.\n"
    )
    inv = _inventory_with("cli/daemon/iterators/lesson_author.py")
    findings = detect_stale_plan_claims(plan, inv)
    assert len(findings) == 1


def test_no_finding_when_referenced_file_genuinely_missing(tmp_path: Path):
    """Plan claims X is not wired AND X is genuinely not in the inventory.
    This is the legitimate case — no finding."""
    plan = tmp_path / "MASTER_PLAN.md"
    plan.write_text(
        "**Not yet wired:** `cli/daemon/iterators/future_thing.py`\n"
    )
    inv = _inventory_with("cli/daemon/iterators/lesson_author.py")  # different file
    findings = detect_stale_plan_claims(plan, inv)
    assert findings == []


def test_handles_agent_cli_prefix_in_inventory(tmp_path: Path):
    """The cartographer may include the 'agent-cli/' prefix on paths.
    The detector should strip/match across both forms."""
    plan = tmp_path / "MASTER_PLAN.md"
    plan.write_text(
        "**Not yet wired:** `cli/daemon/iterators/lesson_author.py`\n"
    )
    inv = _inventory_with("agent-cli/cli/daemon/iterators/lesson_author.py")
    findings = detect_stale_plan_claims(plan, inv)
    assert len(findings) == 1


def test_finds_multiple_distinct_stale_claims(tmp_path: Path):
    plan = tmp_path / "MASTER_PLAN.md"
    plan.write_text(
        "**Not yet wired:** `a.py`\n"
        "\n"
        "Wiring deferred for `b.py`\n"
    )
    inv = _inventory_with("a.py", "b.py")
    findings = detect_stale_plan_claims(plan, inv)
    assert len(findings) == 2
