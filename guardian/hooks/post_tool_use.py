#!/usr/bin/env python3
"""Guardian PostToolUse hook — auto-marks Read tool calls for stale-adr-guard.

Reads tool invocation JSON from stdin and, if the tool was Read,
records the file path via guardian.gate.mark_file_read. The
stale-adr-guard rule in the PreToolUse hook consults this record to
decide whether MASTER_PLAN.md and AUDIT_FIX_PLAN.md have been seen
this session before allowing an ADR write.

Fails open on any error — never blocks Claude Code itself.
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
            return 0
        payload = json.loads(raw)
    except Exception:
        return 0

    tool_name = payload.get("tool_name", "") or payload.get("toolName", "")
    if tool_name != "Read":
        return 0

    tool_input = payload.get("tool_input", {}) or payload.get("toolInput", {})
    file_path = tool_input.get("file_path", "")
    if not file_path:
        return 0

    try:
        from guardian.gate import mark_file_read
        mark_file_read(file_path)
    except Exception:
        pass

    return 0


if __name__ == "__main__":
    sys.exit(main())
