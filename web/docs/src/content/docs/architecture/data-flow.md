---
title: Data Flow
description: How data moves between the daemon, Telegram bot, AI agent, and exchange.
---

## Data Stores

The system uses several persistent stores, all on the local filesystem:

| Store | Path | Format | Purpose |
|-------|------|--------|---------|
| Thesis files | `data/thesis/*.json` | JSON | Conviction, direction, SL/TP per market |
| Memory DB | `data/memory/memory.db` | SQLite | Events, learnings, observations, action log, trade lessons (FTS5) |
| Working state | `data/memory/working_state.json` | JSON | ATR values, current prices, escalation counters |
| Candle cache | `data/candles/candle_cache.db` | SQLite | OHLCV data for technical calculations |
| Agent memory | `data/agent_memory/MEMORY.md` | Markdown | Agent's persistent memory (topics + index) |
| Chat history | `data/daemon/chat_history.jsonl` | JSONL | Full message history, append-only |
| Authority | `data/authority.json` | JSON | Per-asset agent delegation |
| Markets config | `data/config/markets.yaml` | YAML | Market registry — instruments, rules, clearinghouse |

---

## Write Authority

Every write to shared state has exactly one canonical writer:

| State | Writer | Other processes |
|-------|--------|----------------|
| `data/thesis/` | Claude Code (human) / AI agent | Read-only |
| `data/memory/memory.db` | Daemon iterators / AI agent | Read via context harness |
| `data/memory/working_state.json` | Heartbeat daemon | Read by all |
| `data/authority.json` | Claude Code (human) / Telegram `/authority` | Read-only |
| `data/config/markets.yaml` | Claude Code (human) | Read-only |

---

## Tick Flow

Each daemon tick (~120s) follows this sequence:

```
1. Clock fires (cli/daemon/clock.py)
2. TickContext builds: fetches account state, prices, thesis files
3. Each iterator receives the TickContext and runs independently
4. Iterators write to memory.db, send Telegram alerts, place orders
5. working_state.json updated with latest ATR, prices
6. Next tick waits for configured interval
```

---

## Telegram Input Routing

```
User input
    │
    ├── Starts with "/" → slash command handler
    │       └── Deterministic Python code
    │           Direct HyperLiquid API call
    │           Zero AI credits
    │
    └── Free text → AI agent
            └── Build system prompt (AGENT.md + SOUL.md + memory)
                Inject context (thesis, positions, calendar)
                Stream response via SSE to Telegram
                Execute tool calls in parallel
                Write to chat_history.jsonl
```

---

## Memory Backup

The memory database is backed up hourly with atomic snapshots:

- Location: `data/memory/backups/`
- Retention: 24 hourly, 7 daily, 4 weekly
- Restore: `python -m cli.main memory restore --backup <path>`

See [Memory Restore Drill](/operations/runbook/) for the full restore procedure.
