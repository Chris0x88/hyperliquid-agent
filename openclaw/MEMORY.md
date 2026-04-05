# Agent Persistent State

## Architecture (v4 — 2026-04-05)

- **NO MCP.** MCP was removed. All AI runs through `cli/telegram_agent.py` + `cli/agent_runtime.py`.
- **NO OpenClaw gateway.** The AI agent is embedded directly in the Telegram bot.
- **NO `hl` CLI for the agent.** Tools are Python functions, not CLI commands.
- Agent memory lives in `data/agent_memory/` (MEMORY.md index + topic files).
- Tools defined in `cli/agent_tools.py`, implementations in `common/tools.py`.
- System prompt from `openclaw/AGENT.md` + `openclaw/SOUL.md`.
- Model configured via `/models` command, stored in `data/config/model_config.json`.

## What Changed (2026-04-05)

- Built embedded agent runtime ported from Claude Code architecture
- 22 tools: trading, codebase, web search, memory, system, introspection
- Parallel tool execution, SSE streaming, context compaction, memory dream
- Self-improvement: agent can read/edit its own code (with user approval)
