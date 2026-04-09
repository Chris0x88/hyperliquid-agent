---
kind: telegram_command
last_regenerated: 2026-04-09 16:05
command: /lessonauthorai
submodule: lessons
ai_dependent: true
tags:
  - command
  - ai
---
# Command: `/lessonauthorai`

**Submodule**: `lessons`

**AI-dependent**: ✅ yes — name ends in `ai` per CLAUDE.md rule

## Description

Author pending lesson candidates: hand them to the agent and persist.

AI-dependent — uses Claude Haiku via _call_anthropic in telegram_agent.
Per CLAUDE.md slash-command rule, the `ai` suffix is required because
this command's output (the lesson summary, analysis, tags) is written
by the model.

Usage:
    /lessonauthorai          — author the next 3 pending candidates
    /lessonauthorai 1        — author 1
    /lessonauthorai all      — author every pending candidate (capped at 25
                               to keep the bot responsive)

## See also

- Source: [`cli/telegram_commands/lessons.py`](../../cli/telegram_commands/lessons.py)
- Registered in HANDLERS dict + `_set_telegram_commands` + `cmd_help` + `cmd_guide`

## Human notes

<!-- HUMAN:BEGIN -->
_Add hand-written context here._
<!-- HUMAN:END -->
