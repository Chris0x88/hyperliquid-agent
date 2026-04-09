---
kind: architecture
tags:
  - architecture
  - package-map
---

# Package Map

Directory layout of `agent-cli/` with per-package responsibilities.
Auto-generated vault pages live in this directory structure under
`docs/vault/`; the real source code lives in the paths listed below.

## The source tree

```
agent-cli/
├── agent/              prompts (AGENT.md, SOUL.md, reference/)
├── cli/                Telegram bot, embedded agent runtime, daemon
│   ├── daemon/         clock, tiers, iterators
│   │   └── iterators/  36 daemon iterators (auto-indexed)
│   ├── telegram_commands/  submodule split of telegram_bot.py
│   ├── agent_runtime.py    embedded Claude Code runtime port
│   ├── agent_tools.py      TOOL_DEFS + dispatchers (27 tools)
│   ├── telegram_bot.py     4,600-line monolith (being split)
│   └── telegram_agent.py   agent I/O adapter (Anthropic + OpenRouter)
├── common/             shared infrastructure
│   ├── authority.py        per-asset delegation (agent/manual/off)
│   ├── conviction_engine.py  Druckenmiller sizing
│   ├── markets.py          MarketRegistry (per-market config)
│   ├── memory.py           memory.db + lessons FTS5
│   ├── heartbeat.py        2-min launchd-triggered daemon
│   ├── secure_store.py     AES-256-GCM secret vault
│   └── tools.py            pure read tools for the agent
├── modules/            domain logic (pure, no I/O where possible)
│   ├── action_queue.py     user-action queue (nudges)
│   ├── entry_critic.py     deterministic trade grading
│   ├── feedback_store.py   append-only /feedback + /todo event log
│   ├── lesson_engine.py    lesson dataclass + parser
│   ├── oil_botpattern.py   sub-system 5 strategy engine
│   └── ... (many more)
├── parent/             exchange layer + risk
│   ├── hl_proxy.py         HyperLiquid SDK wrapper
│   └── risk_manager.py     protection chain
├── execution/          order routing + TWAP
├── guardian/           dev meta-system (drift detection, review gate)
├── scripts/            one-off scripts (e.g. build_vault.py)
├── data/               runtime state (NEVER committed except configs)
│   ├── config/         kill switches + per-subsystem settings
│   ├── thesis/         per-market thesis JSONs (the Chris contract)
│   ├── memory/         memory.db + hourly backups
│   ├── research/       journal.jsonl, catalysts, bot_patterns, ...
│   ├── daemon/         chat_history.jsonl, pid files, tick logs
│   ├── supply/         supply disruption ledger
│   ├── heatmap/        liquidity zones + cascades
│   ├── feedback.jsonl  /feedback event log (append-only forever)
│   └── todos.jsonl     /todo event log (append-only forever)
├── docs/               documentation
│   ├── plans/          active + parked + archived workstreams
│   │   └── archive/    append-only plan snapshots
│   ├── wiki/           living architecture docs
│   │   ├── build-log.md    append-only milestones
│   │   ├── architecture/   versioned architecture specs
│   │   ├── components/     per-component deep dives
│   │   ├── decisions/      ADRs 1-14
│   │   ├── operations/     runbooks
│   │   └── trading/        domain knowledge
│   └── vault/          ← YOU ARE HERE (Obsidian vault)
└── tests/              pytest suite (3,000+ tests)
```

## Per-package purpose

### `agent/` — prompts only
`AGENT.md` + `SOUL.md` + `reference/`. This is where the agent's
"personality" lives — rules, tool descriptions, response format. Small
files, hand-edited, capped at 20KB each per NORTH_STAR P10 to protect
the system prompt from a runaway dream cycle.

**Touch carefully**: these files are loaded into every LLM call.
Per CLAUDE.md: "Do not modify these files casually."

### `cli/` — interface + runtime
The Telegram bot, the embedded agent runtime, and the daemon clock.
The 4,600-line `telegram_bot.py` is being split into
`cli/telegram_commands/*.py` submodules wedge-by-wedge (the monolith
split). Entry points: `cli.telegram_bot:run()` (bot loop),
`cli.commands.daemon:daemon_start()` (clock + iterators).

**Key gotcha**: every new iterator must be BOTH registered in
`cli/daemon/tiers.py` AND in `cli/commands/daemon.py:daemon_start()`.
Skipping the second step is a silent bug that shipped for memory_backup
and was caught by a parallel agent's side audit. See the `⚠️
REGISTRATION GAP` warnings on auto-generated iterator pages.

### `common/` — shared infrastructure
Low-level shared modules that multiple packages import. Keep this
package "pure" — no knowledge of Telegram, no knowledge of specific
strategies. `authority.py`, `conviction_engine.py`, `markets.py`,
`memory.py`, `heartbeat.py`, `secure_store.py`.

### `modules/` — domain logic
Per-subsystem modules: `entry_critic.py`, `feedback_store.py`,
`lesson_engine.py`, `oil_botpattern.py`, `action_queue.py`, etc.
These are the "smart" modules that encode trading logic, lesson
authoring, critique rendering, etc. They're pure-ish: read from disk,
compute, return structured results. No direct Telegram sends and no
direct exchange calls — those go through the iterators.

### `parent/` — exchange adapter + risk
`hl_proxy.py` is the HyperLiquid SDK wrapper. `risk_manager.py` is the
protection chain. These are the "system's hands" — the code that
actually touches the exchange.

### `guardian/` — dev meta-system
Auto-runs during Claude Code sessions to detect drift (orphans,
parallel tracks, Telegram completeness gaps, stale plan claims). NOT
part of the trading runtime. See `guardian/guide.md` and
[[plans/GUARDIAN_PLAN]].

### `data/` — runtime state
Most paths under `data/` are gitignored per CLAUDE.md "no personal
data in git" — only `data/config/*.json` and `data/config/*.yaml`
are tracked (explicit allowlist in the pre-commit hook). The
`data/thesis/*.json` files are the **Chris contract**: he writes
conviction + reasoning; the daemon reads and executes.

### `docs/` — documentation
- `plans/` — active, parked, archived workstreams
- `wiki/` — living architecture docs (narrative)
- `vault/` — ← this Obsidian vault (navigable structural map)

## Per-package CLAUDE.md

Each package has its own `CLAUDE.md` that routes future sessions to
the right files and flags gotchas:

- `cli/CLAUDE.md` — Telegram bot + agent runtime gotchas
- `cli/daemon/CLAUDE.md` — known iterators + tier system
- `common/CLAUDE.md` — shared infra
- `modules/CLAUDE.md` — domain module inventory
- `parent/CLAUDE.md` — exchange layer + risk manager

## See also

- [[Overview]] — system architecture narrative
- [[Tier-Ladder]] — daemon tier system
- [[Authority-Model]] — per-asset delegation
- [[Data-Discipline]] — P10 retrieval bounds
