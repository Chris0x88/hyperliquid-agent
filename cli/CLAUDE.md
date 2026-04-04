# cli/ — Commands, Telegram Bot, Interactive Menu, AI Agent, Tools

The primary interface layer. Telegram bot with 31 commands + interactive button menu, AI agent with triple-mode tool-calling, position management write commands, and the MCP server.

## Key Areas

### Telegram Bot (v3.2 — Interactive Menu System)

| File | Lines | Purpose |
|------|-------|---------|
| `telegram_bot.py` | ~2700 | 31 command handlers, interactive button menu, callback router (model/approve/reject/mn:), write commands (/close /sl /tp), AI routing |
| `telegram_agent.py` | ~850 | OpenRouter integration, triple-mode tool-calling, context pipeline, candle refresh (1h/4h/1d) |
| `agent_tools.py` | ~700 | 12 tools (7 READ, 5 WRITE with approval), pending action store + cleanup |

### Interactive Menu System

Entry: `/menu` or `/start` → button grid adapts to your actual positions.

```
/menu (main)
├── [Position buttons] → position detail
│   ├── [Close] [SL] [TP] → approval flow
│   ├── [Chart 4h/24h/7d]
│   └── [Technicals] → full signal engine
├── [Orders] [PnL]
├── [Watchlist] → coin grid → market detail
└── [Tools] → Status/Health/Diag/Models/Authority/Memory
```

Button callbacks use `mn:` prefix, routed by `_handle_menu_callback()`. Menu navigation edits messages in-place (no chat flooding). Every button has a slash command fallback.

### Write Commands (with approval flow)

| Command | What it does | Approval |
|---------|-------------|----------|
| `/close BTC` | Market close position | Yes |
| `/sl BTC 65500` | Set stop-loss trigger order | Yes |
| `/tp BTC 72000` | Set take-profit trigger order | Yes |

All use `DirectHLProxy` methods: `market_order()`, `place_trigger_order()`, `place_tp_trigger_order()`. Approval reuses `store_pending()`/`pop_pending()` from agent_tools.py.

### Signal Engine

`/market <coin>` fires the full signal engine:
1. Refreshes candles for 1h, 4h, 1d via `_refresh_candle_cache_for_market()`
2. `build_snapshot()` computes all indicators
3. `render_signal_summary()` produces actionable analysis:
   - Multi-timeframe confluence, exhaustion/capitulation detection
   - RSI divergence, BB squeeze, volume flow, volatility regime
   - Position-specific guidance (supports/against your position)

### Order Display

Uses `frontendOpenOrders` API (not basic `openOrders`) — returns `orderType`, `triggerPx`, `tpsl`, `reduceOnly`. Orders labeled as 🛡 SL, 🎯 TP, or BUY/SELL. `sz=0` displayed as "whole position". Position detail shows SL/TP coverage analysis.

### Triple-Mode Tool Calling

1. Native `tool_calls` (paid models) → execute via `agent_tools.execute_tool()`
2. Regex `[TOOL: name {args}]` (free models) → `_parse_text_tool_calls()`
3. Python code blocks (free models) → AST parser `common/code_tool_parser.py`

Fallback chain: native → regex → code blocks. All converge at execution.

### Context Pipeline

Every AI message: fetch account state → refresh candles (1h/4h/1d for ALL watchlist + position coins) → build_multi_market_context with 3500 token budget → inject as LIVE CONTEXT.

Position-aware: coins with open positions automatically included even if not watchlisted.

### Infrastructure

- **Pending action cleanup:** `cleanup_expired_pending()` runs every 60s in polling loop
- **Position cache:** 5s TTL for rapid menu navigation
- **Candle cache:** 1h freshness check before any snapshot build
- **Single instance:** PID file + pgrep scan (pacman pattern)

### UI Portability

`common/renderer.py` defines `Renderer` ABC with `TelegramRenderer` and `BufferRenderer`. Future web app: implement `WebRenderer`, migrate commands to accept `renderer` instead of `(token, chat_id)`. Migration is incremental — 5 commands at a time.

## Current Status (v3.2)
- Telegram bot: 31 handlers + interactive menu + 5 write tools + signal engine
- AI agent: 12 tools, triple-mode calling, approval gates
- Context: fresh 1h/4h/1d candles, position-aware, 3500 token budget
- Orders: frontendOpenOrders API, SL/TP labels, coverage analysis
- Renderer interface exists for future web app portability
- 1631 tests passing
