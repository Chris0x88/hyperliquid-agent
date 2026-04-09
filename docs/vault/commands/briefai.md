---
kind: telegram_command
last_regenerated: 2026-04-09 16:05
command: /briefai
submodule: telegram_bot (inline)
ai_dependent: true
tags:
  - command
  - ai
---
# Command: `/briefai`

**Submodule**: `telegram_bot (inline)`

**AI-dependent**: ✅ yes — name ends in `ai` per CLAUDE.md rule

## Description

AI-INFLUENCED brief — same as `/brief` plus the THESIS line and
hardcoded CATALYSTS list. Marked with the `ai` suffix because the thesis
text and catalyst calendar are seeded by AI/research, not pure code.

## See also

- Source: inline in [`cli/telegram_bot.py`](../../cli/telegram_bot.py) — candidate for extraction to a submodule in future Telegram monolith wedges
- Registered in HANDLERS dict + `_set_telegram_commands` + `cmd_help` + `cmd_guide`

## Human notes

<!-- HUMAN:BEGIN -->
_Add hand-written context here._
<!-- HUMAN:END -->
