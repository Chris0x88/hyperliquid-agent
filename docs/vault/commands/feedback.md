---
kind: telegram_command
last_regenerated: 2026-04-09 16:05
command: /feedback
submodule: telegram_bot (inline)
ai_dependent: false
tags:
  - command
  - deterministic
---
# Command: `/feedback`

**Submodule**: `telegram_bot (inline)`

**AI-dependent**: ❌ no — deterministic, pure code

## Description

Submit, list, search, resolve, dismiss, tag, or show feedback.

Usage:
    /feedback <text>                     — add a new feedback item
    /feedback list [open|all|resolved]   — list (default: open)
    /feedback search <query>             — substring search
    /feedback resolve <id> [note]        — mark resolved
    /feedback dismiss <id> [note]        — mark won't-fix
    /feedback tag <id> <tag>             — attach a tag
    /feedback show <id>                  — full detail + event history

Historical: this is an event-sourced append-only log. Rows are
NEVER rewritten in place. See modules/feedback_store.py.

## See also

- Source: inline in [`cli/telegram_bot.py`](../../cli/telegram_bot.py) — candidate for extraction to a submodule in future Telegram monolith wedges
- Registered in HANDLERS dict + `_set_telegram_commands` + `cmd_help` + `cmd_guide`

## Human notes

<!-- HUMAN:BEGIN -->
_Add hand-written context here._
<!-- HUMAN:END -->
