---
kind: telegram_command
last_regenerated: 2026-04-09 16:36
command: /disrupt
submodule: telegram_bot (inline)
ai_dependent: false
tags:
  - command
  - deterministic
---
# Command: `/disrupt`

**Submodule**: `telegram_bot (inline)`

**AI-dependent**: ❌ no — deterministic, pure code

## Description

Manually append a supply disruption.

Usage: /disrupt <type> <location> [volume] [unit] [status] [date] ["notes"]
Example: /disrupt refinery Volgograd 200000 bpd active 2026-04-08 "drone strike"
Sub-system 2 (supply ledger).

## See also

- Source: inline in [`cli/telegram_bot.py`](../../cli/telegram_bot.py) — candidate for extraction to a submodule in future Telegram monolith wedges
- Registered in HANDLERS dict + `_set_telegram_commands` + `cmd_help` + `cmd_guide`

## Human notes

<!-- HUMAN:BEGIN -->
_Add hand-written context here._
<!-- HUMAN:END -->
