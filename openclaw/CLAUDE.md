# openclaw/ — OpenClaw Agent Workspace

This is the workspace for the hl-trader OpenClaw agent (@HyperLiquidOpenClaw_bot on Telegram). The agent runs on cheap OpenRouter models — it reads thesis, discusses with Chris, and can make quick adjustments.

**CRITICAL: Never modify `~/.openclaw/openclaw.json` or any files in `~/.openclaw/` — that's Chris's entire AI agent ecosystem with multiple agents and a company of AI workers. Only modify files in THIS directory.**

**Note: OpenClaw gateway has been bypassed (v2 decision).** The AI chat now runs directly via `cli/telegram_agent.py` with OpenRouter, not through the OpenClaw gateway. This workspace is still read by the legacy gateway path but is no longer the primary AI interface.

## Key Files

| File | Purpose |
|------|---------|
| `AGENT.md` | Core instructions: use MCP tools first, never bash commands |
| `AGENTS.md` | Session startup protocol, tool usage guide |
| `SOUL.md` | Response protocol: tool selection, confidence levels, formatting |
| `IDENTITY.md` | Name ("HyperLiquid Trader"), emoji, Telegram markdown rules |
| `USER.md` | Chris's profile: petroleum engineer, timezone, account sizes |
| `BOOTSTRAP.md` | First session startup: load skills, read MCP tools, greet |
| `HEARTBEAT.md` | Currently empty (Claude Code handles periodic monitoring) |
| `STRATEGIST.md` | Strategy generation playbook |
| `TOOLS.md` | MCP tools reference table and research file locations |
| `MEMORY.md` | Persistent state: active rules, learnings, known issues |

## Current AI Architecture (v3)

The primary AI path is now:
```
Telegram free text → telegram_bot.py → telegram_agent.py → OpenRouter
                                                          → 9 agent tools
                                                          → context pipeline
```

The OpenClaw path (legacy):
```
Telegram DM → OpenClaw gateway → hl-trader agent → MCP server → 17 tools
```

Both paths read the same thesis files and exchange data. The v3 path is richer (context pipeline, tool-calling, approval gates).

## MCP Server Configuration

In `agent-cli/openclaw.json`:
```json
{
  "mcp": [{
    "name": "hl-trading",
    "command": ".venv/bin/python",
    "args": ["-m", "cli.main", "mcp", "serve"],
    "cwd": "/Users/cdi/Developer/HyperLiquid_Bot/agent-cli"
  }]
}
```

17 tools: market_context, account, status, analyze, get_candles, agent_memory, trade_journal, trade, log_bug, log_feedback, diagnostic_report, daemon_status, strategies, setup_check, cache_stats, run_strategy, daemon_start.

## Agent Auth Profile

`~/.openclaw/agents/hl-trader/agent/auth-profiles.json` — must have valid OpenRouter key. This is the ONE file outside the project that may be touched, for credential sync only.

## Fix Procedure (when legacy agent stops responding)

1. Check auth profile (most common): if empty, copy from default agent
2. Check gateway log for ETIMEDOUT: `openclaw gateway restart`
3. After code changes: always restart gateway

## Upstream
- OpenClaw Gateway routes Telegram DMs here (legacy)
- v3: `telegram_agent.py` reads AGENT.md + SOUL.md for system prompt

## Downstream
- MCP server reads `common/thesis.py`, `parent/hl_proxy.py`
- Thesis updates write to `data/thesis/`
