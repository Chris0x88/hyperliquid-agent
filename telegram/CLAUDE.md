# telegram/ — Telegram Bot Interface

Telegram-specific UI layer. Commands, menus, approval flows, message dispatch.

## Key Files

| File | Purpose |
|------|---------|
| `bot.py` | Command handlers (`cmd_*`), HANDLERS dict, polling loop |
| `agent.py` | Telegram adapter for AI agent — routes to `agent/runtime.py`, handles streaming |
| `api.py` | Low-level Telegram Bot API wrapper (send, edit, delete, callbacks) |
| `memory.py` | `send_telegram()`, `format_position_summary()` — direct Telegram API dispatch helpers |
| `menu.py` | Interactive inline keyboard menus (`mn:` callback prefix) |
| `approval.py` | Write-command approval flow (inline keyboard confirm/cancel) |
| `handler.py` | Two-way polling, command queue |
| `commands/` | Extracted command implementations (activate, readiness, lessons, etc.) |

## Interface Abstraction

4 commands already use the `Renderer` ABC pattern (status, price, orders, health) — these are interface-agnostic. The remaining ~70 still use `(token, chat_id)`.

- `common/renderer.py` — Renderer ABC (TelegramRenderer + BufferRenderer)
- `exchange/helpers.py` — Generic exchange data helpers (NOT in this package)

When adding a second interface (Discord, web chat), create another top-level dir and implement the Renderer ABC.

## Adding a Command

1. Add `def cmd_name(token, chat_id, args)` in `bot.py` or `commands/`
2. Register in HANDLERS dict (both `/cmd` and bare `cmd` forms)
3. Add to `_set_telegram_commands()` list
4. Add to `cmd_help()` and `cmd_guide()`

## Gotchas

- Menu callbacks use `mn:` prefix, routed by `menu.py`
- Write commands (/close /sl /tp) require approval via `approval.py`
- Single-instance enforcement: PID file + pgrep scan
