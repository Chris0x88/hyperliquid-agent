"""Guardian sweep orchestrator — runs the Tier 1 pipeline end-to-end.

Called by:
- SessionStart hook (directly or via a background sub-agent)
- The /guardian slash command
- Manual invocation: `python -m guardian.sweep`

Produces:
- state/inventory.json + map.mmd + map.md
- state/drift_report.json + drift_report.md
- state/friction_report.json + friction_report.md
- state/sweep.log (append-only)
- state/current_report.md (minimal — Phase 5 sub-agent will replace this)
"""
from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def is_enabled() -> bool:
    return os.environ.get("GUARDIAN_ENABLED", "1") != "0"


def _log_line(state_dir: Path, msg: str) -> None:
    try:
        state_dir.mkdir(parents=True, exist_ok=True)
        with (state_dir / "sweep.log").open("a", encoding="utf-8") as f:
            f.write(f"{datetime.now(timezone.utc).isoformat()} {msg}\n")
    except OSError:
        pass


def run_sweep(repo_root: Path, state_dir: Path | None = None) -> dict[str, Any]:
    """Run cartographer → drift → friction → compile current_report.md.

    Returns a summary dict:
        {modules, drift_p0, drift_p1, friction_p0, friction_p1, duration_s}
    or {skipped: True} if Guardian is globally disabled.
    """
    if not is_enabled():
        return {"skipped": True, "reason": "GUARDIAN_ENABLED=0"}

    if state_dir is None:
        state_dir = repo_root / "guardian" / "state"
    state_dir.mkdir(parents=True, exist_ok=True)

    start = time.monotonic()
    _log_line(state_dir, "sweep start")

    # --- Tier 1: cartographer ---
    from guardian.cartographer import build_inventory, write_inventory
    try:
        inventory = build_inventory(repo_root)
        write_inventory(inventory, state_dir)
        _log_line(state_dir, f"cartographer ok — {inventory['stats']['module_count']} modules")
    except Exception as e:
        _log_line(state_dir, f"cartographer error: {type(e).__name__}: {e}")
        inventory = {"modules": [], "edges": [], "telegram": {}, "iterators": [], "stats": {}}

    # --- Tier 1: drift ---
    from guardian.drift import build_drift_report, write_drift_report
    prev_path = state_dir / "inventory.prev.json"
    prev_inventory = None
    if prev_path.exists():
        try:
            prev_inventory = json.loads(prev_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            pass
    try:
        drift_report = build_drift_report(inventory, prev_inventory)
        write_drift_report(drift_report, state_dir)
        _log_line(state_dir, f"drift ok — {drift_report['summary']['total']} findings")
    except Exception as e:
        _log_line(state_dir, f"drift error: {type(e).__name__}: {e}")
        drift_report = {"summary": {"p0_count": 0, "p1_count": 0, "total": 0}, "orphans": [], "parallel_tracks": [], "telegram_gaps": [], "plan_mismatches": []}

    # --- Tier 1: friction ---
    from guardian.friction import build_friction_report, write_friction_report
    feedback_path = repo_root / "data" / "feedback.jsonl"
    chat_path = repo_root / "data" / "daemon" / "chat_history.jsonl"
    try:
        friction_report = build_friction_report(
            feedback_path=feedback_path,
            chat_history_path=chat_path,
        )
        write_friction_report(friction_report, state_dir)
        _log_line(state_dir, f"friction ok — {friction_report['summary']['total']} findings")
    except Exception as e:
        _log_line(state_dir, f"friction error: {type(e).__name__}: {e}")
        friction_report = {"summary": {"p0_count": 0, "p1_count": 0, "total": 0}, "corrections": [], "errors": []}

    # --- Assemble minimal current_report.md (Phase 5 sub-agent will replace this) ---
    _write_current_report(state_dir, inventory, drift_report, friction_report)

    duration = time.monotonic() - start
    _log_line(state_dir, f"sweep done in {duration:.2f}s")

    return {
        "modules": inventory.get("stats", {}).get("module_count", 0),
        "drift_p0": drift_report.get("summary", {}).get("p0_count", 0),
        "drift_p1": drift_report.get("summary", {}).get("p1_count", 0),
        "friction_p0": friction_report.get("summary", {}).get("p0_count", 0),
        "friction_p1": friction_report.get("summary", {}).get("p1_count", 0),
        "duration_s": round(duration, 2),
    }


def _write_current_report(
    state_dir: Path,
    inventory: dict[str, Any],
    drift_report: dict[str, Any],
    friction_report: dict[str, Any],
) -> None:
    """Compile a minimal current_report.md from the tier-1 outputs.

    Phase 5 replaces this with a sub-agent synthesis. Until then this is a
    straightforward concatenation of the high-severity findings.
    """
    stats = inventory.get("stats", {})
    drift_sum = drift_report.get("summary", {})
    fric_sum = friction_report.get("summary", {})

    lines = [
        "# Guardian Current Report",
        "",
        f"Generated: {datetime.now(timezone.utc).isoformat()}",
        "",
        "## State",
        f"- {stats.get('module_count', 0)} Python modules",
        f"- {stats.get('telegram_handler_count', 0)} Telegram handlers",
        f"- {stats.get('iterator_count', 0)} daemon iterators",
        "",
        "## Drift",
        f"- {drift_sum.get('p0_count', 0)} P0, {drift_sum.get('p1_count', 0)} P1, {drift_sum.get('total', 0)} total",
    ]

    # Include up to 3 P0 drift findings
    p0_drift = [f for f in (drift_report.get("orphans", []) + drift_report.get("parallel_tracks", []) + drift_report.get("telegram_gaps", []) + drift_report.get("plan_mismatches", [])) if f.get("severity") == "P0"][:3]
    if p0_drift:
        lines.append("")
        lines.append("### Top drift P0")
        for f in p0_drift:
            name = f.get("name") or f.get("command") or f.get("a") or f.get("reference") or "?"
            lines.append(f"- `{name}` — {f.get('reason', '')}")

    lines.extend([
        "",
        "## Friction",
        f"- {fric_sum.get('p0_count', 0)} P0, {fric_sum.get('p1_count', 0)} P1, {fric_sum.get('total', 0)} total",
    ])

    p0_fric = [c for c in friction_report.get("corrections", []) if c.get("severity") == "P0"][:3]
    if p0_fric:
        lines.append("")
        lines.append("### Top friction P0")
        for c in p0_fric:
            lines.append(f"- `{c['subject']}` corrected {c['count']} times")

    lines.extend([
        "",
        "_Phase 5 will replace this with a sub-agent synthesis._",
        "",
    ])

    (state_dir / "current_report.md").write_text("\n".join(lines))


if __name__ == "__main__":
    repo_root = Path(__file__).resolve().parents[1]
    summary = run_sweep(repo_root)
    print(json.dumps(summary, indent=2))
