---
kind: telegram_command
last_regenerated: 2026-04-09 16:05
command: /news
submodule: telegram_bot (inline)
ai_dependent: false
tags:
  - command
  - deterministic
---
# Command: `/news`

**Submodule**: `telegram_bot (inline)`

**AI-dependent**: ❌ no — deterministic, pure code

## Description

Show the last 10 catalysts ranked by severity DESC, created_at DESC.

Deterministic — reads data/news/catalysts.jsonl directly, no AI.
Sub-system 1 (news ingest). See docs/plans/OIL_BOT_PATTERN_01_NEWS_INGESTION_PLAN.md.

## See also

- Source: inline in [`cli/telegram_bot.py`](../../cli/telegram_bot.py) — candidate for extraction to a submodule in future Telegram monolith wedges
- Registered in HANDLERS dict + `_set_telegram_commands` + `cmd_help` + `cmd_guide`

## Human notes

<!-- HUMAN:BEGIN -->
_Add hand-written context here._
<!-- HUMAN:END -->
