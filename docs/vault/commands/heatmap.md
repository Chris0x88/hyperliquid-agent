---
kind: telegram_command
last_regenerated: 2026-04-09 14:08
command: /heatmap
submodule: telegram_bot (inline)
ai_dependent: false
tags:
  - command
  - deterministic
---
# Command: `/heatmap`

**Submodule**: `telegram_bot (inline)`

**AI-dependent**: ❌ no — deterministic, pure code

## Description

Show the latest stop/liquidity heatmap snapshot.

Sub-system 3 (stop/liquidity heatmap). Deterministic — reads
data/heatmap/{zones,cascades}.jsonl directly. NOT AI-driven.

Optional argument: instrument symbol (default BRENTOIL).

## See also

- Source: inline in [`cli/telegram_bot.py`](../../cli/telegram_bot.py) — candidate for extraction to a submodule in future Telegram monolith wedges
- Registered in HANDLERS dict + `_set_telegram_commands` + `cmd_help` + `cmd_guide`

## Human notes

<!-- HUMAN:BEGIN -->
_Add hand-written context here._
<!-- HUMAN:END -->
