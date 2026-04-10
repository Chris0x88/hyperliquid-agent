---
title: Telegram Bot
description: The real-time dashboard — slash commands hit the exchange directly, free-text routes to the AI agent.
---

## Architecture

The Telegram bot (`cli/telegram_bot.py`) is a long-lived polling process:

- **Poll interval:** 2 seconds
- **Single-instance enforcement:** PID file + pgrep scan; kills any existing process on startup
- **Command dispatch:** Handler registry maps `/command` strings to `cmd_*` functions
- **Callback routing:** Inline keyboard callbacks via `model:`, `approve:`, `reject:`, `mn:` prefixes
- **AI routing:** Any message not matching a slash command delegates to `telegram_agent.py`

---

## Command Categories

Commands are authoritative in source (`def cmd_*` in `telegram_bot.py`). Categories:

| Category | Commands |
|----------|---------|
| Portfolio | `/portfolio`, `/price`, `/orders`, `/pnl`, `/position` |
| Analysis | `/market <coin>`, `/chart`, `/powerlaw` |
| Management | `/close`, `/sl`, `/tp` (approval-gated write commands) |
| Watchlist | `/watchlist`, `/addmarket`, `/removemarket` |
| Authority | `/delegate`, `/reclaim`, `/authority` |
| System | `/health`, `/diag`, `/models`, `/memory`, `/thesis` |
| Meta | `/help`, `/commands`, `/guide`, `/bug`, `/feedback` |

Commands ending in `ai` (e.g., `/briefai`) invoke the AI agent. All others are pure Python.

---

## Interactive Menu System

`/menu` or `/start` opens a button grid that adapts to current positions:

```
/menu
├── [Position buttons] → detail → [Close] [SL] [TP] [Chart] [Technicals]
├── [Orders] [PnL]
├── [Watchlist] → coin grid → market detail
└── [Tools] → Status / Health / Diag / Models / Authority / Memory
```

Menu navigation edits messages in-place — no chat flooding. Every button has a slash command fallback.

---

## Write Command Approval Flow

Write commands require confirmation via inline keyboard before execution:

| Command | Action | Requires approval |
|---------|--------|------------------|
| `/close <coin>` | Market close position | Yes |
| `/sl <coin> <price>` | Set stop-loss trigger | Yes |
| `/tp <coin> <price>` | Set take-profit trigger | Yes |

---

## Signal Engine

`/market <coin>` fires the full technical signal engine:

1. Refreshes candles (1h/4h/1d) via candle cache
2. `build_snapshot()` computes indicators across all timeframes
3. `render_signal_summary()` produces:
   - Multi-timeframe confluence score
   - Exhaustion/capitulation detection
   - RSI divergence signals
   - Bollinger Band squeeze
   - Volume flow analysis
   - Position-specific guidance (long/short/flat)

---

## Slash Command Checklist

When adding any new command, ALL of these surfaces must be updated:

1. `cli/telegram_bot.py` — add `def cmd_<name>(token, chat_id, args)` handler
2. `HANDLERS` dict — register both `/cmd` and bare `cmd` forms (and aliases)
3. `_set_telegram_commands()` list — add to Telegram menu UI
4. `cmd_help()` — add one-line entry under the right section
5. `cmd_guide()` — add to user-facing section if applicable
6. If AI-dependent, command name MUST end in `ai`
7. Tests in `tests/test_telegram_bot.py` for non-trivial behavior
