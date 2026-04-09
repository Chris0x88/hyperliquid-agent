---
kind: telegram_command
last_regenerated: 2026-04-09 14:08
command: /disruptions
submodule: telegram_bot (inline)
ai_dependent: false
tags:
  - command
  - deterministic
---
# Command: `/disruptions`

**Submodule**: `telegram_bot (inline)`

**AI-dependent**: ❌ no — deterministic, pure code

## Description

List top 10 active supply disruptions by confidence*volume.

Sub-system 2 (supply ledger). Deterministic — reads disruptions.jsonl directly.

## See also

- Source: inline in [`cli/telegram_bot.py`](../../cli/telegram_bot.py) — candidate for extraction to a submodule in future Telegram monolith wedges
- Registered in HANDLERS dict + `_set_telegram_commands` + `cmd_help` + `cmd_guide`

## Human notes

<!-- HUMAN:BEGIN -->
_Add hand-written context here._
<!-- HUMAN:END -->
