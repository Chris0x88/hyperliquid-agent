# Agent Workspace

This workspace configures the embedded AI agent running inside the Telegram bot.

**There is NO MCP, NO `hl` CLI, NO OpenClaw gateway.** The agent runs directly via `cli/telegram_agent.py` with Python function tools.

## Key Files

- `AGENT.md` — System prompt: trading rules, tool list, coin names, formatting
- `SOUL.md` — Response protocol: confidence levels, Telegram formatting, safety rules
- `TOOLS.md` — Tool reference (points to AGENT.md)
- `MEMORY.md` — This file: persistent state tracker

## How the Agent Works

1. User sends free text to Telegram bot
2. Bot routes to `cli/telegram_agent.py`
3. Agent runtime (`cli/agent_runtime.py`) builds system prompt + live context
4. Calls model (Anthropic direct or OpenRouter) with tool definitions
5. Tool loop: up to 12 iterations, READ tools auto-execute, WRITE tools need approval
6. Response streamed to Telegram
