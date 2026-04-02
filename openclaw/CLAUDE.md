# openclaw/ — OpenClaw Agent Workspace

This is the workspace for the hl-trader OpenClaw agent (@HyperLiquidOpenClaw_bot on Telegram). The agent runs on cheap OpenRouter models (NOT Opus) — it reads thesis, discusses with Chris, and can make quick adjustments. It is NOT the primary thesis writer.

**CRITICAL: Never modify `~/.openclaw/openclaw.json` or any files in `~/.openclaw/` — that's Chris's entire AI agent ecosystem with multiple agents and a company of AI workers. Only modify files in THIS directory.**

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

## MCP Server Configuration

The MCP server is defined in the PARENT directory at `agent-cli/openclaw.json`:
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

The MCP server exposes 17 tools (Phase 2 adds 2 more):
- `market_context` — comprehensive market brief (primary tool)
- `account` — live account state
- `status` — quick position/PnL view
- `analyze` — technical analysis
- `trade` — place orders
- `live_price` — quick price check (Phase 2)
- `update_thesis` — write conviction updates (Phase 2)
- Plus 10 more for memory, journal, diagnostics, strategies

## Agent Auth Profile

The agent's API credentials live at `~/.openclaw/agents/hl-trader/agent/auth-profiles.json`. This must have a valid OpenRouter key (synced from the default agent). Without it, the agent can't call any LLM and won't respond.

## Telegram Binding

In `~/.openclaw/openclaw.json`:
```json
{"agentId": "hl-trader", "match": {"channel": "telegram", "accountId": "hl-trader"}}
```
Bot: @HyperLiquidOpenClaw_bot. DM only. Chris's user ID: 5219304680.

## Agent's Role

The agent is the **voice** of the system, not the brain:
- Reads thesis files (written by Chris via Claude Code Opus)
- Reads live market data via MCP tools
- Discusses strategy, challenges thesis, suggests trades
- Can update thesis conviction in a pinch (Phase 2: `update_thesis` tool)
- Executes trades if instructed (autonomous mandate)
- Reports via Telegram in clean formatting

## Upstream
- OpenClaw Gateway routes Telegram DMs here
- MCP tools call into `cli/mcp_server.py`

## Downstream
- MCP server reads `common/thesis.py`, `parent/hl_proxy.py`
- Thesis updates write to `data/thesis/`

## Current Status
- Agent responds on Telegram (auth profile fixed this session)
- MCP server starts with 17 tools (mcp package installed this session)
- Agent serves stale data because thesis files aren't updated (fixed in Phase 2)

## Future Direction (Phase 2)
- Add `update_thesis` and `live_price` MCP tools
- Update TOOLS.md and AGENT.md to document new tools
- Agent can then give live prices and persist conviction updates
