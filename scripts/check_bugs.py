#!/usr/bin/env python3
"""Check for open bugs in data/bugs.md and output them for Claude Code to fix.

Usage:
    python scripts/check_bugs.py              # Print open bugs
    python scripts/check_bugs.py --json       # JSON output for automation
    python scripts/check_bugs.py --resolve "Bug Title"  # Mark a bug as resolved

This script is designed to be called by Claude Code hooks or scheduled tasks.
When bugs are reported via Telegram (/bug) or OpenClaw (log_bug tool), they
land in data/bugs.md. This script reads them back.
"""
from __future__ import annotations

import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

BUGS_FILE = Path("data/bugs.md")


def parse_bugs() -> list[dict]:
    """Parse bugs.md into structured entries."""
    if not BUGS_FILE.exists():
        return []

    content = BUGS_FILE.read_text()
    bugs = []
    current: dict | None = None

    for line in content.split("\n"):
        # Match bug headers: ## [SEVERITY] Title
        m = re.match(r"^## \[(\w+)\] (.+)$", line)
        if m:
            if current:
                bugs.append(current)
            current = {
                "severity": m.group(1).lower(),
                "title": m.group(2).strip(),
                "reported": "",
                "source": "",
                "status": "open",
                "description": "",
            }
        elif current:
            # Parse metadata lines
            if line.startswith("- **Reported:**"):
                current["reported"] = line.split(":**", 1)[1].strip()
            elif line.startswith("- **Source:**"):
                current["source"] = line.split(":**", 1)[1].strip()
            elif line.startswith("- **Status:**"):
                current["status"] = line.split(":**", 1)[1].strip()
            elif line.startswith("- **Description:**"):
                current["description"] = line.split(":**", 1)[1].strip()

    if current:
        bugs.append(current)

    return bugs


def get_open_bugs() -> list[dict]:
    """Get only open (unresolved) bugs."""
    return [b for b in parse_bugs() if b["status"] == "open"]


def resolve_bug(title: str) -> bool:
    """Mark a bug as resolved in bugs.md."""
    if not BUGS_FILE.exists():
        return False

    content = BUGS_FILE.read_text()
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    # Find the bug and update its status
    updated = content.replace(
        f"- **Status:** open",
        f"- **Status:** resolved ({now})",
        1,  # only first match
    )

    if updated == content:
        # Try matching with the title
        pattern = re.escape(title)
        lines = content.split("\n")
        found = False
        for i, line in enumerate(lines):
            if re.search(pattern, line, re.IGNORECASE):
                found = True
                # Find the status line after this header
                for j in range(i + 1, min(i + 6, len(lines))):
                    if "**Status:** open" in lines[j]:
                        lines[j] = f"- **Status:** resolved ({now})"
                        break
                break
        if found:
            updated = "\n".join(lines)
        else:
            return False

    BUGS_FILE.write_text(updated)
    return True


def main():
    if "--resolve" in sys.argv:
        idx = sys.argv.index("--resolve")
        if idx + 1 < len(sys.argv):
            title = sys.argv[idx + 1]
            if resolve_bug(title):
                print(f"Resolved: {title}")
            else:
                print(f"Bug not found: {title}")
        return

    bugs = get_open_bugs()

    if "--json" in sys.argv:
        print(json.dumps(bugs, indent=2))
        return

    if not bugs:
        print("No open bugs.")
        return

    print(f"Open bugs ({len(bugs)}):\n")
    for b in bugs:
        sev = b["severity"].upper()
        print(f"  [{sev}] {b['title']}")
        if b["description"]:
            print(f"    {b['description'][:120]}")
        if b["reported"]:
            print(f"    Reported: {b['reported']}")
        print()


if __name__ == "__main__":
    main()
