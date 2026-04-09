---
kind: telegram_command
last_regenerated: 2026-04-09 14:08
command: /todo
submodule: telegram_bot (inline)
ai_dependent: false
tags:
  - command
  - deterministic
---
# Command: `/todo`

**Submodule**: `telegram_bot (inline)`

**AI-dependent**: ❌ no — deterministic, pure code

## Description

Add, list, search, done, dismiss, or show todos.

Usage:
    /todo                         — list open todos
    /todo <description>           — add a new todo
    /todo list [open|all|done]    — list with status filter
    /todo search <query>          — substring search
    /todo done <id>               — mark done
    /todo dismiss <id> [note]     — mark dismissed
    /todo show <id>               — full detail + event history

Event-sourced append-only. See modules/feedback_store.py.

## See also

- Source: inline in [`cli/telegram_bot.py`](../../cli/telegram_bot.py) — candidate for extraction to a submodule in future Telegram monolith wedges
- Registered in HANDLERS dict + `_set_telegram_commands` + `cmd_help` + `cmd_guide`

## Human notes

<!-- HUMAN:BEGIN -->
_Add hand-written context here._
<!-- HUMAN:END -->
