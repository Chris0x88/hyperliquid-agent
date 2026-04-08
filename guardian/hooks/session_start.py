#!/usr/bin/env python3
"""Guardian SessionStart hook — compact state injection + lazy sweep.

If guardian/state/current_report.md is absent or older than 24h, run the
tier-1 sweep synchronously before injecting state. The sweep is pure
stdlib and typically <5s on the current repo.

Sub-agent dispatch for natural-language synthesis is Claude's job — the
hook leaves a marker for Claude to pick up if GUARDIAN_SUBAGENTS_ENABLED
is set. Claude then dispatches a background sub-agent via the Agent tool.
Fails open on any error.
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path


def is_enabled() -> bool:
    return os.environ.get("GUARDIAN_ENABLED", "1") != "0"


def is_subagent_dispatch_enabled() -> bool:
    return os.environ.get("GUARDIAN_SUBAGENTS_ENABLED", "1") != "0"


def _report_age_hours(path: Path) -> float:
    return (time.time() - path.stat().st_mtime) / 3600.0


def _maybe_run_sweep(repo_root: Path, state_dir: Path) -> None:
    """Run a sweep if state is stale. Silent on all errors."""
    report = state_dir / "current_report.md"
    should_run = False
    if not report.exists():
        should_run = True
    else:
        try:
            if _report_age_hours(report) > 24:
                should_run = True
        except OSError:
            should_run = True

    if not should_run:
        return

    try:
        # Make guardian importable
        sys.path.insert(0, str(repo_root))
        from guardian.sweep import run_sweep
        run_sweep(repo_root=repo_root, state_dir=state_dir)
    except Exception:
        pass


def build_summary(
    state_dir: Path | None = None,
    repo_root: Path | None = None,
) -> str:
    """Build the compact summary string to inject into Claude's context.

    Returns an empty string if Guardian is disabled. Never raises.
    """
    if not is_enabled():
        return ""

    try:
        if repo_root is None:
            repo_root = Path(__file__).resolve().parents[2]
        if state_dir is None:
            state_dir = repo_root / "guardian" / "state"

        state_dir = Path(state_dir)
        repo_root = Path(repo_root)

        # Reset the per-session reads tracker for the stale-adr-guard rule
        try:
            from guardian.gate import reset_session_reads
            reset_session_reads()
        except Exception:
            pass

        # Lazy sweep if state is missing or stale
        _maybe_run_sweep(repo_root, state_dir)

        if not state_dir.exists():
            return "## Guardian\nNo state directory — Guardian has not yet been initialized.\n"

        report = state_dir / "current_report.md"
        if not report.exists():
            return "## Guardian\nNo current report. Sweep did not produce output — check guardian/state/sweep.log.\n"

        age_hours = _report_age_hours(report)
        stale_marker = ""
        if age_hours > 24:
            stale_marker = f" ⚠️ stale ({age_hours:.0f}h old)"

        body = report.read_text(encoding="utf-8")
        lines = body.split("\n")
        if len(lines) > 200:
            body = "\n".join(lines[:200]) + f"\n\n... ({len(lines) - 200} more lines in guardian/state/current_report.md)"

        header = f"## Guardian{stale_marker}\n\n"
        if is_subagent_dispatch_enabled():
            header += (
                "_If the tier-1 report above is missing the natural-language "
                "synthesis Claude normally writes, dispatch a `guardian-sweep` "
                "background sub-agent via the Agent tool (general-purpose, "
                "run_in_background=true) to refresh `guardian/state/current_report.md`._\n\n"
            )

        return header + body + "\n"

    except Exception as e:
        return f"## Guardian\n(hook error: {type(e).__name__}; see guardian/state/sweep.log)\n"


def main() -> int:
    summary = build_summary()
    if summary:
        sys.stdout.write(summary)
    return 0


if __name__ == "__main__":
    sys.exit(main())
