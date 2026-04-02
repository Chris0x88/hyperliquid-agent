# cli/ — Commands, Telegram Bot, AI Agent, Tools

The primary interface layer. Contains 23 CLI commands, the Telegram bot (25 handlers), the AI agent with tool-calling, and the MCP server. This is the v2/v3 heart of the system.

## Key Areas

### Telegram Bot + AI Agent (v2/v3 core)

| File | Lines | Purpose |
|------|-------|---------|
| `telegram_bot.py` | ~1800 | Polling loop (2s), 25 command handlers, callback router (model/approve/reject), AI message routing |
| `telegram_agent.py` | ~760 | OpenRouter integration, tool-calling loop (max 3), context pipeline, chat history sanitization |
| `agent_tools.py` | ~550 | 9 tools (7 READ auto-execute, 2 WRITE with approval gates), pending action store (5min TTL) |

**Data flow:** User message → `telegram_bot.py` (polling) → free text routed to `telegram_agent.py` → builds context (account + positions + technicals + thesis + memory) → calls OpenRouter with tool definitions → tool results fed back → response to Telegram.

**Dual-mode tool calling:** Paid models use native `tool_calls`. Free models use text-based `[TOOL: name {args}]` parsed by `_parse_text_tool_calls()`. Both paths converge at `execute_tool()`.

**WRITE tool approval:** `place_trade` and `update_thesis` store pending actions, send Telegram inline keyboard [Approve/Reject], execute only on approval. 5-min TTL auto-expire.

**Coin name normalization (RECURRING BUG):** xyz clearinghouse returns `xyz:BRENTOIL`, native returns `BTC`. Use `_coin_matches()` or compare both `name` and `name.replace("xyz:", "")`. This has caused silent failures multiple times.

### CLI Commands (23 total)

Entry point: `cli/main.py` — Typer app. Run via `hl <command>`.

| Command | File | Purpose |
|---------|------|---------|
| `hl status` | `commands/status.py` | Positions, PnL, risk |
| `hl trade` | `commands/trade.py` | Manual order placement |
| `hl daemon` | `commands/daemon.py` | Monitoring loop |
| `hl reflect` | `commands/reflect.py` | Performance review |
| `hl mcp` | `commands/mcp.py` | MCP server (`hl mcp serve`) |
| `hl telegram` | `commands/telegram.py` | Telegram bot control |
| + 17 more | `commands/` | account, strategies, guard, radar, pulse, apex, wallet, setup, skills, journal, keys, markets, data, backtest, heartbeat_cmd, commands |

### MCP Server

`cli/mcp_server.py` — FastMCP with 17 tools. Launch: `hl mcp serve`. Used by OpenClaw agent (legacy) and potentially future integrations.

### Other Files

| File | Purpose |
|------|---------|
| `strategy_registry.py` | 27 registered strategies |
| `config.py` | TradingConfig + YAML loading |
| `engine.py` | Legacy single-strategy engine |
| `hl_adapter.py` | DirectHLProxy wrapper for SDK |
| `chart_engine.py` | Price chart generation (matplotlib) |
| `telegram_handler.py` | Legacy handler (not actively used) |

## Upstream
- `main.py` routes to all commands
- launchd launches telegram_bot.py
- OpenClaw gateway calls MCP server (legacy path)

## Downstream
- Commands call into `common/`, `modules/`, `parent/`
- AI agent calls `common/context_harness.py`, `common/market_snapshot.py`
- Agent tools call `parent/hl_proxy.py`, `common/thesis.py`, `modules/candle_cache.py`

## Current Status (v3)
- All 23 CLI commands work
- Telegram bot running with 25 handlers + AI router + inline keyboards
- AI agent running with 9 tools, dual-mode calling, approval gates
- MCP server starts with 17 tools
- Context pipeline: account + positions + technicals + thesis + memory (3000 token budget)
- 18 curated models (10 free, 8 paid) switchable via /models

## Testing
```bash
.venv/bin/python -m pytest tests/test_config.py tests/test_engine.py tests/test_strategy_registry.py -x -q
# Note: telegram_agent.py and agent_tools.py lack test coverage (gap)
```
