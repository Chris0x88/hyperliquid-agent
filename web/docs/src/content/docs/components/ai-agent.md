---
title: AI Agent
description: Embedded Claude agent runtime with parallel tools, streaming responses, persistent memory, and session-token authentication.
---

## What It Is

The AI agent is a Claude Code architecture ported to Python. It runs as a full agent runtime inside the bot, not an API-glued chatbot. Capabilities include:

- **Parallel tool calls** — multiple tools execute simultaneously in one response
- **SSE streaming** — responses stream to Telegram in real time
- **Context compaction** — auto-summarizes history when approaching the context limit
- **Persistent memory** — flat-file index plus SQLite FTS5 for lessons

Source: `cli/agent_runtime.py`, `cli/telegram_agent.py`

---

## Authentication

The agent uses **session tokens only** — never API keys. This is non-negotiable:

- API keys cost money per token and would bankrupt the user at scale
- Session tokens are free (same mechanism as the claude.ai web interface)
- The session token is stored in `~/.openclaw/agents/default/agent/auth-profiles.json`

---

## System Prompt

The agent's personality, trading rules, and operational boundaries live in two files:

| File | Purpose |
|------|---------|
| `agent/AGENT.md` | System prompt: context harness, available tools, response protocol, formatting rules |
| `agent/SOUL.md` | Trading philosophy, risk rules, market-specific constraints, conviction framework |

Both are injected into every agent session. The agent reads thesis files, account state, and trade history before responding.

---

## Tools

The agent uses Python function tools defined in `cli/agent_tools.py`. Not MCP — this is a recurring point of confusion.

Tools share one implementation with three renderers (Telegram, web, test). Key categories:

| Category | Examples |
|----------|---------|
| Market data | Price, OHLCV candles, funding rates, open interest |
| Account | Positions, equity, open orders |
| Trade execution | Place/cancel orders (requires delegated authority) |
| Thesis | Read/write thesis files, update conviction |
| Memory | Search lesson corpus, write observations |
| Calendar | Check upcoming events (EIA, OPEC, Fed) |
| Code execution | Run Python in the project venv |

---

## Context Injection

Before each response, the agent's context harness injects:

1. **Account state** — current positions, equity, margin usage
2. **Active thesis files** — with conviction levels and staleness flags
3. **Calendar context** — upcoming EIA reports, OPEC meetings, Fed decisions
4. **Top lessons** — FTS5 search over the lesson corpus, ranked by relevance to the current situation
5. **Recent messages** — last N Telegram messages for conversational context
6. **Working state** — current ATR values, prices, market snapshots

---

## Memory Architecture

```
data/agent_memory/
  MEMORY.md              <-- Flat index file, read every session
                              No topics/ subdirectory

data/memory/memory.db    <-- SQLite database
  lessons table           <-- FTS5 full-text search over trade lessons
  events table            <-- Timestamped events log
  action_log              <-- Trade decisions + rationale
  summaries               <-- Compacted session summaries
```

Key points:

- `MEMORY.md` is a flat index with no subdirectories. It is read at the start of every agent session.
- `memory.db` uses SQLite FTS5 for fast full-text search over the lesson corpus.
- Lessons are written by the `lesson_author` daemon iterator and by the agent itself during REFLECT.
- The agent can search lessons with the `search_lessons` tool, which queries the FTS5 index.

---

## REFLECT Loop

The REFLECT process evaluates recent trades and extracts lessons:

1. Pulls recent closed positions from `action_log`
2. Grades entries via the entry critic
3. Writes lessons to the FTS5 corpus in `memory.db`
4. Surfaces patterns for the agent to review in future sessions

This creates a feedback loop: the agent learns from each trade, and top lessons are injected into future decisions via context injection.

---

## Chat History

Conversation history is persisted to `data/daemon/chat_history.jsonl` as newline-delimited JSON. Each entry includes the message, role, timestamp, and any tool calls/results. The `/chathistory` command exposes recent history in Telegram.

---

## When Does AI Run?

The AI agent only runs in three scenarios:

1. **Free-text Telegram message** — anything not starting with `/`
2. **`ai`-suffixed command** — e.g., `/briefai`, `/brutalreviewai`, `/lessonauthorai`
3. **Daemon-triggered analysis** — e.g., thesis evaluation, lesson authoring

Every other interaction is deterministic Python. Zero AI credits consumed for slash commands.
