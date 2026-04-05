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
- Slight indirection cost: commands now call `renderer.send_text()` instead of `tg_send()`.
- 5 commands migrated so far (status, price, orders, health, menu).
