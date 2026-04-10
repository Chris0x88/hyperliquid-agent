---
kind: telegram_command
last_regenerated: 2026-04-09 16:36
command: /critique
submodule: entry_critic
ai_dependent: false
tags:
  - command
  - deterministic
---
# Command: `/critique`

**Submodule**: `entry_critic`

**AI-dependent**: ❌ no — deterministic, pure code

## Description

Show recent entry critiques from data/research/entry_critiques.jsonl.

Usage:
    /critique             — most recent critique (full detail)
    /critique 5           — last 5 critiques (compact list)
    /critique BTC         — last 5 critiques filtered to instrument
    /critique BTC 10      — last 10 critiques filtered to instrument

Deterministic — reads the JSONL written by the entry_critic iterator
when each new position was detected. No AI.

## See also

- Source: [`cli/telegram_commands/entry_critic.py`](../../cli/telegram_commands/entry_critic.py)
- Registered in HANDLERS dict + `_set_telegram_commands` + `cmd_help` + `cmd_guide`

## Human notes

<!-- HUMAN:BEGIN -->
_Add hand-written context here._
<!-- HUMAN:END -->
