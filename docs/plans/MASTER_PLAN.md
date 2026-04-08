# HyperLiquid Trading System — Master Plan

> **Start every session by reading this file + the relevant package `CLAUDE.md`.**
> **For system knowledge: `docs/wiki/`** | **For build history: `docs/wiki/build-log.md`**

## What This System Is

A Financial Assistant + Trading Research Agent + Risk Manager. One product, three roles:
1. **Portfolio copilot** — Chris brings the thesis (petroleum engineering edge), system executes with discipline
2. **Research agent** — Proactively hunts for trades, challenges thesis, learns from outcomes
3. **Risk manager** — Autonomous stops, leverage management, ruin prevention

## Current Phase: Oil Bot Pattern System (Sub-Systems 1 + 2 SHIPPED; dry-run pending)

Hardening is complete. All F-items and H-items from `docs/plans/AUDIT_FIX_PLAN.md`
shipped (see build-log 2026-04-07/08). The Oil Bot Pattern system is the active
workstream. Two sub-systems have shipped in parallel with the Trade Lesson Layer
(separate workstream owned by the Lessons session — see build-log 2026-04-09).

**Active plan:** `docs/plans/OIL_BOT_PATTERN_SYSTEM.md` — 6-sub-system plan approved 2026-04-09.

**Shipped 2026-04-09:**
- ✅ Sub-system 1 — News & Catalyst Ingestion
  - Spec: `docs/plans/OIL_BOT_PATTERN_01_NEWS_INGESTION.md`
  - Plan: `docs/plans/OIL_BOT_PATTERN_01_NEWS_INGESTION_PLAN.md`
  - Shipped behind kill switch `data/config/news_ingest.json` with `severity_floor: 5`
    dry-run posture. 24h dry-run gate auto-promotes to `severity_floor: 3` via the
    scheduled task `oil-botpattern-s1-promote-severity-floor` (fires 2026-04-10 06:00 AEST).
- ✅ Sub-system 2 — Supply Disruption Ledger
  - Spec: `docs/plans/OIL_BOT_PATTERN_02_SUPPLY_LEDGER.md`
  - Plan: `docs/plans/OIL_BOT_PATTERN_02_SUPPLY_LEDGER_PLAN.md`
  - 4 Telegram commands: `/supply`, `/disruptions`, `/disrupt`, `/disrupt-update`

**Next to build:**
- Sub-system 3 — Stop-hunt / liquidity heatmap (HL L2 orderbook analysis)
- Then: sub-system 4 (bot-pattern classifier), 5 (strategy engine with scoped
  oil-short relaxation), 6 (self-tune harness — partially pre-built by the
  Trade Lesson Layer work)

For the deferred research-app build (parked), see
`docs/wiki/decisions/011-two-app-architecture-research-sibling.md` —
status `Proposed`, no implementation.

### What's Next After Oil Bot Pattern

- **Phase 4: Self-Improving** — Auto-tuning, catalyst calendar, convergence tracking
- See `docs/plans/PHASE_4_SELF_IMPROVING.md`
- **Optional: ADR-011 research-app** — only if Chris greenlights it

## What Has Shipped

### v4 (2026-04-05) — embedded agent runtime
- **Embedded agent runtime** — `cli/agent_runtime.py` ported from Claude Code (parallel tools, streaming, compaction, dream)
- Tool inventory: see `cli/agent_tools.py` (`TOOL_DEFS`)
- **Agent memory** — persistent `data/agent_memory/` with auto-loaded MEMORY.md
- **Self-improvement** — agent can read/edit its own code with user approval
- **Wiki documentation system** — single source of truth in `docs/wiki/`, MAINTAINING.md guide

### Phase 3 (REFLECT loop) — SHIPPED
The autoresearch daemon iterator now runs `ReflectEngine` on a regular
cycle and emits round-trip metrics into the daemon log and memory.
See `cli/daemon/iterators/autoresearch.py`. The Phase 3 plan document
remains as the historical spec — its `Status: Planned` field is stale.

### Audit hardening (2026-04-07) — DONE
- All F-items and H-items shipped. See `docs/plans/AUDIT_FIX_PLAN.md` status table
  and build-log entries 2026-04-07 and 2026-04-08 for full detail.
- Alert format + equity reporting postmortem shipped 2026-04-08 (Bugs A-D, 45 tests).
- Liquidation monitor thresholds recalibrated 2026-04-09 (19.8x avg leverage).

### Trade lesson layer (2026-04-09) — data layer SHIPPED, wiring deferred
- `modules/lesson_engine.py`: pure `Lesson` dataclass, sentinel-wrapped
  prompt, strict response parser. Shipped in `7ac7bea`.
- `common/memory.py`: `lessons` table + `lessons_fts` FTS5 virtual table +
  append-only trigger + `log_lesson`/`get_lesson`/`search_lessons`/
  `set_lesson_review` helpers. Shipped in `7ac7bea`.
- Full test coverage + `import re` bug fix (caught by the tests) shipped in
  `3027b00`. See build-log 2026-04-09 entry for the parallel-session
  convergence story.
- **Not yet wired:** `cli/daemon/iterators/lesson_author.py`, `search_lessons`
  + `get_lesson` in `cli/agent_tools.py`, `RECENT RELEVANT LESSONS` section
  in `cli/agent_runtime.py:build_system_prompt()`, `/lessons` + `/lesson`
  + `/lessonsearch` in `cli/telegram_bot.py`, `agent/reference/tools.md`
  + `agent/AGENT.md` updates. Design in
  `.claude/plans/bubbly-juggling-fountain.md`. Deferred behind the current
  active phase (Oil Bot Pattern System).

## Open Questions / Priorities

- SILVER and GOLD thesis stale — conviction auto-clamped
- Streaming not yet wired to Telegram output (helper exists, needs integration into main flow)
- Dream consolidation runs but doesn't yet use agent tools (marks complete only)
- Vault BTC positions are not included in `_fetch_account_state_for_harness()`
  (vault rebalancer manages it independently — minor gap, not yet scoped)
- Lesson layer table is an empty shell until the `lesson_author` iterator
  ships — nothing writes to it in production (see "Trade lesson layer" above)

## Package Map

| Package | CLAUDE.md | Wiki |
|---------|-----------|------|
| `common/` | `common/CLAUDE.md` | [wiki/architecture.md](../wiki/architecture.md) |
| `cli/` | `cli/CLAUDE.md` | [wiki/components/telegram-bot.md](../wiki/components/telegram-bot.md) |
| `cli/daemon/` | `cli/daemon/CLAUDE.md` | [wiki/components/daemon.md](../wiki/components/daemon.md) |
| `modules/` | `modules/CLAUDE.md` | [wiki/components/conviction-engine.md](../wiki/components/conviction-engine.md) |
| `parent/` | `parent/CLAUDE.md` | [wiki/components/risk-manager.md](../wiki/components/risk-manager.md) |
| `agent/` | `agent/AGENT.md` + `SOUL.md` | [wiki/components/ai-agent.md](../wiki/components/ai-agent.md) |

## Session Workflow

```
1. Read this file (MASTER_PLAN.md)
2. Read the relevant package CLAUDE.md for your work
3. If needed, browse docs/wiki/ for deeper context
4. Do the work, run tests, commit
5. If architecture changed: update the relevant wiki page
6. Run /alignment at end of session to verify docs match reality
```

## Critical Rules

1. **NEVER touch `~/.openclaw/`** — Chris's entire AI agent ecosystem
2. **Thesis files are the shared contract** — Chris writes conviction via Opus, daemon reads and executes
3. **Coin name normalization** — xyz clearinghouse returns `xyz:BRENTOIL`, native returns `BTC`. Always handle both.
4. **LONG or NEUTRAL only on oil** — never short
5. **Always add specific files to git** — never `git add -A`
6. **Every position MUST have SL + TP on exchange**
