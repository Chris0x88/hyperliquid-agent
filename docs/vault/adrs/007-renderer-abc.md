---
kind: adr
last_regenerated: 2026-04-09 16:05
adr_file: docs/wiki/decisions/007-renderer-abc.md
tags:
  - adr
  - decision
---
# ADR-007: Renderer ABC for UI Portability

**Source**: [`docs/wiki/decisions/007-renderer-abc.md`](../../docs/wiki/decisions/007-renderer-abc.md)

## Preview

```
# ADR-007: Renderer ABC for UI Portability

**Date:** 2026-04-04
**Status:** Accepted

## Context
All command output was hardcoded to Telegram's `tg_send` functions, making it impossible to reuse command logic for a web dashboard, tests, or CLI output. Testing required mocking Telegram API calls.

## Decision
Create a `Renderer` ABC in `common/renderer.py` following the same Protocol pattern as `venue_adapter.py`. Two implementations ship: `TelegramRenderer` (production, wraps tg_send) and `BufferRenderer` (captures output for tests and future web API). Commands accept a renderer instead of `(token, chat_id)`. Migration is incremental --- 5 commands migrated first, rest follow as touched.

## Consequences
- Tests use `BufferRenderer` and assert on captured messages. No Telegram mocking needed.
- A future `WebRenderer` can serve the same command logic as JSON over HTTP.
- Incremental migration avoids a risky big-bang rewrite of all 31 commands.
```

## Human notes

<!-- HUMAN:BEGIN -->
<!-- HUMAN:END -->
