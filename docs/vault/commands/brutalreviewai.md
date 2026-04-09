---
kind: telegram_command
last_regenerated: 2026-04-09 16:05
command: /brutalreviewai
submodule: brutal_review
ai_dependent: true
tags:
  - command
  - ai
---
# Command: `/brutalreviewai`

**Submodule**: `brutal_review`

**AI-dependent**: ✅ yes — name ends in `ai` per CLAUDE.md rule

## Description

Run the Brutal Review Loop on demand.

AI-dependent — hands the literal BRUTAL_REVIEW_PROMPT.md to the
agent for a deep audit pass. The agent's full output lands on disk
at ``data/reviews/brutal_review_YYYY-MM-DD.md`` and a short summary
posts back to Telegram.

Usage:
    /brutalreviewai            — run the full review pass

Cost: one full agent invocation (Sonnet by default, ~30-60s wall
time, free under session-token auth). Run weekly or on demand
after a major architectural change.

## See also

- Source: [`cli/telegram_commands/brutal_review.py`](../../cli/telegram_commands/brutal_review.py)
- Registered in HANDLERS dict + `_set_telegram_commands` + `cmd_help` + `cmd_guide`

## Human notes

<!-- HUMAN:BEGIN -->
_Add hand-written context here._
<!-- HUMAN:END -->
