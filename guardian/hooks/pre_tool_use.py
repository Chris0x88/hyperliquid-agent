#!/usr/bin/env python3
"""Guardian PreToolUse hook — runs gate.py checks on Edit/Write/Bash.

Reads tool invocation JSON from stdin, runs the gate, writes a result
JSON to stdout. Fails open on any error — the hook never raises.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

# Ensure guardian is importable
_REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO))


def main() -> int:
    try:
        raw = sys.stdin.read()
        if not raw.strip():
            # Nothing to check; allow.
            return 0
        payload = json.loads(raw)
    except Exception:
        # Fail open: can't parse, allow.
        return 0

    tool_name = payload.get("tool_name", "") or payload.get("toolName", "")
    tool_input = payload.get("tool_input", {}) or payload.get("toolInput", {})

    try:
        from guardian.gate import check_tool_use
        result = check_tool_use(tool_name, tool_input)
    except Exception:
        return 0

    if result.allow:
        return 0

    # Blocked — write reason to stdout as JSON, exit 2 (per Claude Code hook convention)
    sys.stdout.write(json.dumps({
        "decision": "block",
        "reason": result.reason or "Guardian gate blocked this action",
        "rule": result.rule or "unknown",
    }))
    return 2


if __name__ == "__main__":
    sys.exit(main())
