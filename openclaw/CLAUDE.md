# openclaw/ — OpenClaw Agent Workspace

Workspace for the hl-trader OpenClaw agent (@HyperLiquidOpenClaw_bot on Telegram). Legacy path — primary AI now runs via `cli/telegram_agent.py`.

**CRITICAL: Never modify `~/.openclaw/openclaw.json` or any files in `~/.openclaw/` — that's Chris's entire AI agent ecosystem.**

## Key Files

| File | Purpose |
|------|---------|
| `AGENT.md` | Core agent instructions |
| `SOUL.md` | Response protocol and formatting |
| `USER.md` | Chris's profile for agent context |
| `TOOLS.md` | MCP tools reference |
| `IDENTITY.md` | Agent name, emoji, Telegram markdown |
| `MEMORY.md` | Persistent state and learnings |

**Deep dive:** [docs/wiki/decisions/003-openclaw-bypass.md](../docs/wiki/decisions/003-openclaw-bypass.md)

## Gotchas

- OpenClaw gateway bypassed (v2 decision) — `telegram_agent.py` calls OpenRouter directly
- Agent auth profile: `~/.openclaw/agents/hl-trader/agent/auth-profiles.json` — only file outside project that may be touched
- MCP server config in `agent-cli/openclaw.json`
- If legacy agent stops: check auth profile first, then gateway log, then restart
