# cli/ — Commands, Telegram Bot, AI Agent, Tools

Primary interface layer. Bot commands, interactive button menu, AI agent with tool-calling, and the MCP server.

## Key Files

| File | Purpose |
|------|---------|
| `telegram_bot.py` | Command handlers (`def cmd_*`), interactive menu (`mn:` callbacks), write commands, AI routing |
| `telegram_agent.py` | OpenRouter integration, triple-mode tool-calling, context pipeline |
| `agent_tools.py` | Tools (READ auto-execute, WRITE with approval), pending action store |
| `mcp_server.py` | MCP server for OpenClaw agent |
| `hl_adapter.py` | DirectHLProxy — exchange adapter with market_order, trigger orders |

**Deep dive:** [docs/wiki/components/telegram-bot.md](../docs/wiki/components/telegram-bot.md) | [docs/wiki/components/ai-agent.md](../docs/wiki/components/ai-agent.md)

## Gotchas

- Single-instance enforcement: PID file + pgrep scan
- Menu callbacks use `mn:` prefix, routed by `_handle_menu_callback()`
- Write commands (/close /sl /tp) require approval via inline keyboard
- Triple-mode tool calling: native → regex → code blocks fallback
- Context pipeline refreshes candles for ALL watchlist + position coins
