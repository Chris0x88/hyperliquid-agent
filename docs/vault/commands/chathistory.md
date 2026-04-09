---
kind: telegram_command
last_regenerated: 2026-04-09 16:05
command: /chathistory
submodule: chat_history
ai_dependent: false
tags:
  - command
  - deterministic
---
# Command: `/chathistory`

**Submodule**: `chat_history`

**AI-dependent**: ❌ no — deterministic, pure code

## Description

``/chathistory`` dispatcher — last N, search, or stats.

Deterministic. Reads only. Never writes or mutates the history file.

## See also

- Source: [`cli/telegram_commands/chat_history.py`](../../cli/telegram_commands/chat_history.py)
- Registered in HANDLERS dict + `_set_telegram_commands` + `cmd_help` + `cmd_guide`

## Human notes

<!-- HUMAN:BEGIN -->
_Add hand-written context here._
<!-- HUMAN:END -->
