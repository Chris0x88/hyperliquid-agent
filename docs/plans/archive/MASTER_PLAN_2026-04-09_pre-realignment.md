<!--
ARCHIVED: 2026-04-09 PM
Reason: Snapshot of MASTER_PLAN.md taken immediately before the
2026-04-09/10 deep-dive review and realignment session. This version
contained STALE CLAIMS that the Trade Lesson Layer was "data layer
shipped, wiring deferred" — in reality wedges 5 + 6 had already shipped
in commits 9094b22 and a65b1e5 and the entire lesson pipeline was
wired end-to-end. Sub-system 4 (bot_classifier) had also shipped after
this version was last updated.

This snapshot is preserved unmodified so future sessions can:
  1. See what the plan said at this exact moment in time.
  2. Compare to current MASTER_PLAN.md to see what drifted and what
     was reconciled.
  3. Reflect on the cost of plan-vs-reality drift (wasted hardening
     session 2026-04-07 was the trigger for the alignment workflow).

DO NOT EDIT. Append-only convention. To update reality, edit
docs/plans/MASTER_PLAN.md and (if appropriate) snapshot a new archive.
-->

# HyperLiquid Trading System — Master Plan

> **Start every session by reading this file + the relevant package `CLAUDE.md`.**
> **For system knowledge: `docs/wiki/`** | **For build history: `docs/wiki/build-log.md`**

## What This System Is

A Financial Assistant + Trading Research Agent + Risk Manager. One product, three roles:
1. **Portfolio copilot** — Chris brings the thesis (petroleum engineering edge), system executes with discipline
2. **Research agent** — Proactively hunts for trades, challenges thesis, learns from outcomes
3. **Risk manager** — Autonomous stops, leverage management, ruin prevention

## Current Phase: Oil Bot Pattern System (Sub-Systems 1 + 2 + 3 + 4 + 5 SHIPPED; kill switches OFF on #5)

Hardening is complete. All F-items and H-items from `docs/plans/AUDIT_FIX_PLAN.md`
shipped (see build-log 2026-04-07/08). The Oil Bot Pattern system is the active
workstream. Five sub-systems have shipped in parallel with the Trade Lesson Layer
(separate workstream owned by the Lessons session — see build-log 2026-04-09).

**Sub-system 5 is registered but INERT on first ship** — both kill switches
(`enabled`, `short_legs_enabled`) default to `false`, and the iterator runs in
REBALANCE + OPPORTUNISTIC tiers only (not WATCH, which is Chris's current
production tier). No trade will be placed by sub-system 5 until Chris flips
`enabled` AND promotes the daemon tier.

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
- ✅ Sub-system 3 — Stop / Liquidity Heatmap
  - Spec: `docs/plans/OIL_BOT_PATTERN_03_LIQUIDITY_HEATMAP.md`
  - Plan: `docs/plans/OIL_BOT_PATTERN_03_LIQUIDITY_HEATMAP_PLAN.md`
  - Pure HL info API. Read-only. No external deps. Polls L2 + OI + funding,
    writes `data/heatmap/{zones,cascades}.jsonl`. Telegram surface: `/heatmap`.
    Kill switch: `data/config/heatmap.json`.
- ✅ Sub-system 4 — Bot-Pattern Classifier
  - Spec: `docs/plans/OIL_BOT_PATTERN_04_BOT_CLASSIFIER.md`
  - First sub-system that consumes multiple streams: combines #1 catalysts,
    #2 supply state, #3 cascades, and candle cache to classify recent moves
    as bot-driven, informed, mixed, or unclear. Heuristic only — NO ML, NO LLM
    (L5 deferred). Writes `data/research/bot_patterns.jsonl`. Telegram
    surface: `/botpatterns`. Kill switch: `data/config/bot_classifier.json`.
- ✅ Sub-system 5 — Oil Bot-Pattern Strategy Engine
  - Spec: `docs/plans/OIL_BOT_PATTERN_05_STRATEGY_ENGINE.md`
  - **The ONLY place in the codebase where shorting BRENTOIL/CL is legal.**
    Conviction sizing (Druckenmiller ladder: edge → notional × leverage,
    max 2.8× equity notional at edge ≥ 0.90) with drawdown circuit breakers
    (3% daily / 8% weekly / 15% monthly) as the ruin floor. Funding-cost
    exit for longs (no time cap); 24h hard cap on shorts. Coexists with
    existing thesis_engine per SYSTEM doc §5. Runs in REBALANCE +
    OPPORTUNISTIC (NOT WATCH). Both kill switches ship OFF. Telegram
    surface: `/oilbot`, `/oilbotjournal`, `/oilbotreviewai`. Spec:
    `docs/plans/OIL_BOT_PATTERN_05_STRATEGY_ENGINE.md`.

**Next to build:**
- Sub-system 6 — Self-tune harness (L2 reflect proposals + L3 pattern
  library + L4 shadow trading). Partially pre-built by the Trade Lesson
  Layer work — the lesson corpus feeds the reflect loop. Needs wedge
  planning to connect the existing pieces.

For the deferred research-app build (parked), see
`docs/wiki/decisions/011-two-app-architecture-research-sibling.md` —
status `Proposed`, no implementation.

### What's Next After Oil Bot Pattern

- **Phase 4: Self-Improving** — Auto-tuning, catalyst calendar, convergence tracking
- See `docs/plans/PHASE_4_SELF_IMPROVING.md`
- **Optional: ADR-011 research-app** — only if Chris greenlights it
- **Dev infrastructure:** Guardian Angel meta-system — `docs/plans/GUARDIAN_PLAN.md` (auto-runs in Claude Code sessions; see `agent-cli/guardian/guide.md`)

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
