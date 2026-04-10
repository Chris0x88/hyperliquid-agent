---
kind: telegram_command
last_regenerated: 2026-04-09 16:36
command: /brief
submodule: telegram_bot (inline)
ai_dependent: false
tags:
  - command
  - deterministic
---
# Command: `/brief`

**Submodule**: `telegram_bot (inline)`

**AI-dependent**: ❌ no — deterministic, pure code

## Description

MECHANICAL brief — fixed code, NO AI content. Portfolio, positions,
orders, market technicals (price/EMA/RSI/trend/liquidity), funding 24h,
chart. Use `/briefai` for the thesis + catalysts version. Per CLAUDE.md
slash commands MUST be fixed code; AI-dependent variants get the `ai`
suffix.

## See also

- Source: inline in [`cli/telegram_bot.py`](../../cli/telegram_bot.py) — candidate for extraction to a submodule in future Telegram monolith wedges
- Registered in HANDLERS dict + `_set_telegram_commands` + `cmd_help` + `cmd_guide`

## Human notes

<!-- HUMAN:BEGIN -->
_Add hand-written context here._
<!-- HUMAN:END -->
