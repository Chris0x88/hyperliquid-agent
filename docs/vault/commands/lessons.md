---
kind: telegram_command
last_regenerated: 2026-04-09 16:36
command: /lessons
submodule: lessons
ai_dependent: false
tags:
  - command
  - deterministic
---
# Command: `/lessons`

**Submodule**: `lessons`

**AI-dependent**: ❌ no — deterministic, pure code

## Description

Show the most recent lessons from the trade lesson corpus.

Deterministic — reads data/memory/memory.db via common.memory.search_lessons.
Optional argument: integer limit (default 10, max 25).
Rejected lessons (reviewed_by_chris = -1) are excluded by default.

## See also

- Source: [`cli/telegram_commands/lessons.py`](../../cli/telegram_commands/lessons.py)
- Registered in HANDLERS dict + `_set_telegram_commands` + `cmd_help` + `cmd_guide`

## Human notes

<!-- HUMAN:BEGIN -->
_Add hand-written context here._
<!-- HUMAN:END -->
