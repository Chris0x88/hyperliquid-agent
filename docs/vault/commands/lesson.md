---
kind: telegram_command
last_regenerated: 2026-04-09 14:08
command: /lesson
submodule: lessons
ai_dependent: false
tags:
  - command
  - deterministic
---
# Command: `/lesson`

**Submodule**: `lessons`

**AI-dependent**: ❌ no — deterministic, pure code

## Description

Show one lesson by id, or approve/reject a lesson.

Usage:
    /lesson <id>           — show the verbatim body
    /lesson approve <id>   — mark reviewed_by_chris = 1 (boost ranking)
    /lesson reject <id>    — mark reviewed_by_chris = -1 (exclude, anti-pattern)
    /lesson unreview <id>  — reset reviewed_by_chris = 0

Deterministic — reads/writes data/memory/memory.db directly, no AI.

## See also

- Source: [`cli/telegram_commands/lessons.py`](../../cli/telegram_commands/lessons.py)
- Registered in HANDLERS dict + `_set_telegram_commands` + `cmd_help` + `cmd_guide`

## Human notes

<!-- HUMAN:BEGIN -->
_Add hand-written context here._
<!-- HUMAN:END -->
