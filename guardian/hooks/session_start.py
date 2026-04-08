#!/usr/bin/env python3
"""Guardian SessionStart hook — injects compact repo state into Claude's context.

Read-only in Phase 1. Phase 5 adds background sub-agent dispatch and lazy sweep.
Fails open (prints empty string) on any error so Claude Code never breaks.
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path


def is_enabled() -> bool:
    """Global Guardian kill switch."""
    return os.environ.get("GUARDIAN_ENABLED", "1") != "0"


def _report_age_hours(path: Path) -> float:
    return (time.time() - path.stat().st_mtime) / 3600.0


def build_summary(
    state_dir: Path | None = None,
    repo_root: Path | None = None,
) -> str:
    """Build the compact summary string to inject into Claude's context.

    Returns an empty string if Guardian is disabled or there's no state.
    Returns a short markdown block otherwise. Never raises.
    """
    if not is_enabled():
        return ""

    try:
        if repo_root is None:
            # Default: guardian/hooks/session_start.py → repo root is two levels up
            repo_root = Path(__file__).resolve().parents[2]
        if state_dir is None:
            state_dir = repo_root / "guardian" / "state"

        state_dir = Path(state_dir)
        if not state_dir.exists():
            return (
                "## Guardian\n"
                "No state directory — Guardian has not yet run. "
                "Next session will generate one.\n"
            )

        report = state_dir / "current_report.md"
        if not report.exists():
            return (
                "## Guardian\n"
                "No current report. Cartographer has not yet written one. "
                "Run `python -m guardian.sweep` to generate.\n"
            )

        age_hours = _report_age_hours(report)
        stale_marker = ""
        if age_hours > 24:
            stale_marker = f" ⚠️ stale ({age_hours:.0f}h old)"

        body = report.read_text(encoding="utf-8")
        # Truncate to first 200 lines to respect hook output budget
        lines = body.split("\n")
        if len(lines) > 200:
            body = (
                "\n".join(lines[:200])
                + f"\n\n... ({len(lines) - 200} more lines in guardian/state/current_report.md)"
            )

        return f"## Guardian{stale_marker}\n\n{body}\n"

    except Exception as e:
        # Fail open: never block the session
        return f"## Guardian\n(hook error: {type(e).__name__}; see guardian/state/sweep.log)\n"


def main() -> int:
    summary = build_summary()
    if summary:
        sys.stdout.write(summary)
    return 0


if __name__ == "__main__":
    sys.exit(main())
