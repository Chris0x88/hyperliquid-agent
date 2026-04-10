---
title: AI Agent
description: Embedded Claude agent runtime — a port of Claude Code architecture with parallel tools, streaming, and persistent memory.
---

## What It Is

The AI agent is a Claude Code architecture ported to Python. It's not an API-glued chatbot — it's a full agent runtime with:

- **Parallel tool calls** — multiple tools execute simultaneously in one response
- **SSE streaming** — responses stream to Telegram in real time
- **Context compaction** — auto-summarizes history when approaching the context limit
- **Persistent memory** — `data/agent_memory/MEMORY.md` survives across sessions
- **autoDream consolidation** — after 24h or 3 sessions, dreams consolidate memory into long-term storage

Source: `cli/agent_runtime.py`, `cli/telegram_agent.py`

---

## Authentication

The agent uses **session tokens only** — never API keys. This is critical:

- API keys cost money per token
- Session tokens are free (same as claude.ai web interface)
- The session token is stored in `~/.openclaw/agents/default/agent/auth-profiles.json`

See [Anthropic Session Token Guide](/operations/security/) for how to obtain and rotate tokens.

---

## System Prompt

The agent's personality and trading rules live in two files:

| File | Purpose |
|------|---------|
| `agent/AGENT.md` | System prompt — context harness, tools, response protocol |
| `agent/SOUL.md` | Trading rules, risk philosophy, market-specific rules |

These are injected into every agent session. The agent reads your codebase, thesis files, and trade history before responding.

---

## Tools

The agent has access to Python function tools (not MCP). Key tools include:

- Market data: price, OHLCV, funding rates, open interest
- Account: positions, equity, orders
- Trade execution: place/cancel orders (requires authority)
- Thesis: read/write thesis files
- Memory: search lesson corpus, write observations
- Calendar: check upcoming events
- Code execution: run Python in the venv

Tools share one implementation with three renderers (Telegram, web, test).

---

## Context Injection

Before each response, the agent's context harness injects:

1. Current account state (positions, equity)
2. Active thesis files with conviction levels
3. Calendar context (upcoming EIA reports, OPEC meetings, Fed decisions)
4. Top 5 lessons from the FTS5 lesson corpus relevant to the current situation
5. Recent Telegram message history (last N messages)
6. Working state (current ATR values, prices)

---

## Memory Architecture

```
data/agent_memory/
├── MEMORY.md           ← Index + active topics (read every session)
└── topics/             ← Long-form topic files (lazy-loaded)

data/memory/memory.db
└── lessons table       ← FTS5 full-text search over trade lessons
    events table        ← Timestamped events log
    action_log          ← Trade decisions + rationale
    summaries           ← Compacted session summaries
```

---

## REFLECT Loop

The REFLECT iterator runs periodically to evaluate recent trades:

1. Pulls recent closed positions from `action_log`
2. Grades entries via the entry critic
3. Writes lessons to the FTS5 corpus
4. Surfaces patterns for the agent to review

This means the agent learns from each trade and injects top lessons into future decisions.

---

## Routing: When Does AI Run?

The AI agent only runs when:
1. A free-text Telegram message is received (not a slash command)
2. A command ending in `ai` is called (e.g., `/briefai`)
3. The daemon triggers an analysis task (e.g., thesis evaluation)

Every other action is deterministic Python — zero AI credits consumed.
