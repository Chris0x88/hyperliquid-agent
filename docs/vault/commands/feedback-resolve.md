---
kind: telegram_command
last_regenerated: 2026-04-09 16:36
command: /feedback_resolve
submodule: telegram_bot (inline)
ai_dependent: false
tags:
  - command
  - deterministic
---
# Command: `/feedback_resolve`

**Submodule**: `telegram_bot (inline)`

**AI-dependent**: ❌ no — deterministic, pure code

## Description

Legacy admin shim — mark feedback as resolved by id, short prefix, or ``all``.

Historical note: the pre-2026-04-09 implementation read the whole
file, mutated entries in memory, and rewrote the file with
``open(path, "w")``. That silently modified the very historical
rows Chris said he values most. This now dispatches to the
append-only event store — primary rows are never touched.

## See also

- Source: inline in [`cli/telegram_bot.py`](../../cli/telegram_bot.py) — candidate for extraction to a submodule in future Telegram monolith wedges
- Registered in HANDLERS dict + `_set_telegram_commands` + `cmd_help` + `cmd_guide`

## Human notes

<!-- HUMAN:BEGIN -->
_Add hand-written context here._
<!-- HUMAN:END -->
