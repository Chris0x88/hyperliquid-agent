---
kind: telegram_command
last_regenerated: 2026-04-09 16:36
command: /lessonsearch
submodule: lessons
ai_dependent: false
tags:
  - command
  - deterministic
---
# Command: `/lessonsearch`

**Submodule**: `lessons`

**AI-dependent**: ❌ no — deterministic, pure code

## Description

BM25-ranked search over the lesson corpus.

Usage: /lessonsearch <query>
Deterministic — reads data/memory/memory.db directly, no AI.

## See also

- Source: [`cli/telegram_commands/lessons.py`](../../cli/telegram_commands/lessons.py)
- Registered in HANDLERS dict + `_set_telegram_commands` + `cmd_help` + `cmd_guide`

## Human notes

<!-- HUMAN:BEGIN -->
_Add hand-written context here._
<!-- HUMAN:END -->
