# Telegram Bot

Real-time Telegram interface that polls every 2 seconds. Slash commands run pure Python against the HyperLiquid API with zero AI credits burned. Only free-text messages route to the AI agent.

## Architecture

`cli/telegram_bot.py` is the main file. It runs as a single long-lived process with:

- **Polling loop** at 2s interval with single-instance enforcement (PID file + pgrep scan)
- **Command dispatch** via a handler registry mapping `/command` to `cmd_*` functions
- **Callback routing** for inline keyboard buttons (`model:`, `approve:`, `reject:`, `mn:` prefixes)
- **AI routing** for any message that does not match a slash command (delegates to `telegram_agent.py`)

## Command Categories

All commands are defined as `cmd_*` functions in `telegram_bot.py`. Rather than listing them here (they change frequently), check the source directly:

- **Portfolio:** `/status`, `/price`, `/orders`, `/pnl`, `/position`
- **Analysis:** `/market <coin>` (full signal engine), `/chart`, `/powerlaw`
- **Management:** `/close`, `/sl`, `/tp` (write commands with approval flow)
- **Watchlist:** `/watchlist`, `/addmarket`, `/removemarket`
- **Authority:** `/delegate`, `/reclaim`, `/authority`
- **System:** `/health`, `/diag`, `/models`, `/memory`, `/thesis`
- **Vault:** `/rebalancer`, `/rebalance`
- **Meta:** `/help`, `/commands`, `/guide`, `/bug`, `/feedback`

See `def cmd_*` in `cli/telegram_bot.py` for the authoritative list.

## Interactive Menu System

`/menu` or `/start` opens a button grid that adapts to current positions:

```
/menu (main)
+-- [Position buttons] -> position detail -> [Close] [SL] [TP] [Chart] [Technicals]
+-- [Orders] [PnL]
+-- [Watchlist] -> coin grid -> market detail
+-- [Tools] -> Status / Health / Diag / Models / Authority / Memory
```

All `mn:` callbacks are routed by `_handle_menu_callback()`. Menu navigation edits messages in-place (no chat flooding). Every button has a slash command fallback.

## Write Commands

| Command | Action | Approval |
|---------|--------|----------|
| `/close <coin>` | Market close position | Yes (inline keyboard) |
| `/sl <coin> <price>` | Set stop-loss trigger order | Yes |
| `/tp <coin> <price>` | Set take-profit trigger order | Yes |

All use `DirectHLProxy` methods. Approval reuses `store_pending()`/`pop_pending()` from `agent_tools.py`.

## Signal Engine

`/market <coin>` fires the full signal engine:
1. Refreshes candles (1h/4h/1d) via candle cache
2. `build_snapshot()` computes indicators across all timeframes
3. `render_signal_summary()` produces multi-timeframe confluence, exhaustion/capitulation detection, RSI divergence, BB squeeze, volume flow, and position-specific guidance

## Single-Instance Enforcement

The bot writes a PID file at startup and kills any existing process. This prevents duplicate bots from running and double-processing messages.
