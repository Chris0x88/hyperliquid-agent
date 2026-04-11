# cli/ — Commands, Telegram Bot, AI Agent, Tools

Primary interface layer. Bot commands, interactive button menu, AI agent with tool-calling, and the MCP server.

## Key Files

| File | Purpose |
|------|---------|
| `telegram_bot.py` | Command handlers (`def cmd_*`), HANDLERS dict, write commands, AI routing |
| `telegram_api.py` | Low-level Telegram Bot API wrapper (send, edit, delete, callbacks) |
| `telegram_hl.py` | HyperLiquid data helpers for Telegram (positions, funding, OI lookups) |
| `telegram_menu.py` | Interactive menu (`mn:` callbacks), button layouts, menu rendering |
| `telegram_approval.py` | Write-command approval flow (inline keyboard confirm/cancel) |
| `telegram_handler.py` | Two-way command handler — polls incoming messages, queues for execution |
| `telegram_agent.py` | Telegram adapter — routes to agent_runtime, handles streaming output, Anthropic/OpenRouter API calls |
| `agent_runtime.py` | **Core agent runtime** — system prompt, parallel tools, SSE streaming, context compaction, memory dream |
| `agent_tools.py` | Agent tools (READ auto-execute, WRITE with approval, DISPLAY bypass LLM), pending action store. Live count: `grep -c '^def ' agent_tools.py` |
| `trade_evaluator.py` | Deterministic trade setup evaluations (short-WTI checklist, calendar alerts) injected into agent context |
| `mcp_server.py` | MCP server for OpenClaw agent |
| `hl_adapter.py` | DirectHLProxy — exchange adapter with market_order, trigger orders |

**Deep dive:** [docs/wiki/components/telegram-bot.md](../docs/wiki/components/telegram-bot.md) | [docs/wiki/components/ai-agent.md](../docs/wiki/components/ai-agent.md)

## Learning Paths

- [Adding a Command](../docs/wiki/learning-paths/adding-a-command.md) — end-to-end guide for new Telegram commands
- [Understanding the AI Agent](../docs/wiki/learning-paths/understanding-ai-agent.md) — agent runtime, tools, context pipeline
- [Understanding Alerts](../docs/wiki/learning-paths/understanding-alerts.md) — how alerts flow from daemon to Telegram

## Gotchas

- Single-instance enforcement: PID file + pgrep scan
- Menu callbacks use `mn:` prefix, routed by `telegram_menu.py`
- Write commands (/close /sl /tp) require approval via `telegram_approval.py`
- Triple-mode tool calling: native -> regex -> code blocks fallback
- Context pipeline refreshes candles for ALL watchlist + position coins
- Agent runtime ported from Claude Code: parallel tools, streaming, compaction, dream
- Anthropic direct API (Opus/Sonnet/Haiku) + OpenRouter fallback
- Agent memory persisted in `data/agent_memory/`
