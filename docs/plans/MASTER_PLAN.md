# HyperLiquid Trading System — Master Plan

> **Read this + the relevant package `CLAUDE.md` at the start of every session.**
> **System knowledge:** `docs/wiki/` · **Build history:** `docs/wiki/build-log.md` · **Past plans:** `docs/plans/archive/`

---

## What This System Is

A **personal trading instrument** for one petroleum engineer, evolving toward a
**multi-market discipline-execution platform**. One product, three roles:

1. **Portfolio copilot** — Chris brings the thesis (deep domain edge starting
   with oil, expanding to all HL markets). The system executes with discipline
   he can't sustain manually.
2. **Research agent** — Hunts catalysts, challenges thesis, recalls past trades,
   replaces gut feel with checkable evidence.
3. **Risk manager** — Mandatory exchange-side stops + take-profits, drawdown
   circuit breakers, ruin prevention. Autonomous when correct, conservative when
   uncertain.

Long-term vision: **Chris has the ideas; the system has the execution.** Compound
wealth as fast as possible without tanking the account, taking outsized risk only
when the edge is large. See `NORTH_STAR.md`.

---

## Current Reality (always reflects HEAD)

| | |
|---|---|
| **Production tier** | WATCH (mainnet, launchd-managed) |
| **Tradeable thesis markets** | BTC, BRENTOIL, GOLD, SILVER (oil + BTC are active edge) |
| **Tracked but not thesis-driven** | Anything with an open position (auto-watchlist, audit F2) |
| **Agent runtime** | Embedded Claude Code port, session-token auth, no API keys |
| **Test suite** | 2,400+ tests, 0 failed (run `pytest tests/ -q`) |
| **Daemon iterators** | See `cli/daemon/iterators/` and `cli/daemon/tiers.py` |
| **Telegram commands** | See `def cmd_*` in `cli/telegram_bot.py` and HANDLERS dict |
| **Agent tools** | See `TOOL_DEFS` in `cli/agent_tools.py` |
| **Memory.db backups** | Hourly atomic snapshots in `data/memory/backups/` (24h/7d/4w retention) |

**What's running on real money right now**: heartbeat dip-add / trim against
thesis files in `data/thesis/`, mandatory exchange-side SL+TP enforcement,
liquidation cushion monitor at 19.8x avg leverage, auto-watchlist tracking
of any open position, lesson corpus retrieval injecting top-5 past lessons
into every agent decision. WATCH tier — no autonomous trade placement
without thesis-driven sizing.

**What's parked behind kill switches** (registered, tested, INERT until
manually flipped): oil_botpattern strategy engine (the only legal short
path on oil), news_ingest dry-run severity floor.

---

## Active Workstreams

### 1. Oil Bot Pattern System — Sub-system 6 (next)

Sub-systems 1–5 shipped. See archive for the historical phase plan.
Sub-system 6 is the **self-tune harness** — it consumes the lesson
corpus, the pattern library, and the bot_classifier output to propose
adjustments to gate thresholds and sizing parameters. Partially
pre-built by the Trade Lesson Layer (corpus + retrieval + dream cycle
already exist). Needs wedge planning to connect.

**Spec**: `docs/plans/OIL_BOT_PATTERN_SYSTEM.md` (master), `docs/plans/OIL_BOT_PATTERN_06_*.md` (when written).

### 2. Multi-Market Expansion (new)

The codebase has oil-shaped assumptions (long-only oil rule, BRENTOIL
roll buffers, oil_botpattern subsystem, supply ledger, oil-knowledge wiki).
The user's edge expands beyond oil. This plan decouples market-specific
logic from the trading core so any HL market can be promoted from
"tracked" to "thesis-driven" via configuration, not code edits.

**Spec**: `docs/plans/MULTI_MARKET_EXPANSION_PLAN.md`.

### 3. Brutal Review Loop (new)

Guardian catches drift continuously but shallow. Alignment is a session
ritual. Neither does what the 2026-04-09 deep-dive review did: a
periodic deep-honesty audit that grades the codebase, finds gaps,
calls out staleness, challenges direction, and produces a brutally
specific action list. This plan defines a cadenced audit loop owned
by a dedicated agent invocation.

**Spec**: `docs/plans/BRUTAL_REVIEW_LOOP.md`.

### 4. Long-term Direction

**Spec**: `docs/plans/NORTH_STAR.md` — vision, principles, what good looks like
in 12 / 24 / 36 months.

---

## Open Questions / Known Gaps

> Things known to be true at HEAD that need attention. Updated when reality
> changes — don't let this section rot. If you fix one, cross it out and add
> a build-log entry explaining what shipped.

- **SILVER + GOLD theses are stale.** Conviction auto-clamped (safe), but the
  system isn't trading those markets at all. Either refresh them or formally
  park them.
- **Streaming agent output is built but not wired to Telegram.** The agent
  thinks for 30+ seconds and the user sees nothing until done. UX paper-cut.
- **Dream consolidation marks complete but does not call agent tools.** Memory
  consolidation works; tool-using consolidation does not.
- **Vault BTC excluded from `_fetch_account_state_for_harness()`.** Vault
  rebalancer manages it independently — minor visibility gap.
- **Lesson corpus has no backup retention strategy beyond the new memory.db
  snapshots.** Snapshots cover the DB but not the candidate files in
  `data/daemon/lesson_candidates/`.
- **`telegram_bot.py` is 4,200+ lines.** Working, monitored by Guardian
  telegram-completeness drift, but should be incrementally split into
  `cli/telegram_commands/` submodules over time.

---

## Package Map

| Package | CLAUDE.md | Wiki |
|---------|-----------|------|
| `common/` | `common/CLAUDE.md` | [wiki/architecture/current.md](../wiki/architecture/current.md) |
| `cli/` | `cli/CLAUDE.md` | [wiki/components/telegram-bot.md](../wiki/components/telegram-bot.md) |
| `cli/daemon/` | `cli/daemon/CLAUDE.md` | [wiki/components/daemon.md](../wiki/components/daemon.md) |
| `modules/` | `modules/CLAUDE.md` | [wiki/components/conviction-engine.md](../wiki/components/conviction-engine.md) |
| `parent/` | `parent/CLAUDE.md` | [wiki/components/risk-manager.md](../wiki/components/risk-manager.md) |
| `agent/` | `agent/AGENT.md` + `SOUL.md` | [wiki/components/ai-agent.md](../wiki/components/ai-agent.md) |
| `guardian/` | (uses `guide.md`) | [wiki/components/guardian.md](../wiki/components/guardian.md) |

---

## Session Workflow

```
1. Read this file (MASTER_PLAN.md) + relevant package CLAUDE.md
2. Run /alignment to surface drift before doing anything
3. Browse docs/wiki/ for deeper context as needed
4. Do the work: TodoWrite for >3 steps, tests for new code, commit per logical unit
5. If architecture changed: update the wiki page (not this file)
6. If MASTER_PLAN itself drifts from reality: archive + rewrite (see Versioning)
7. Run /alignment again at end of session
```

---

## Critical Rules

1. **NEVER touch `~/.openclaw/`** — Chris's entire AI agent ecosystem lives there.
2. **Thesis files are the shared contract.** Chris writes conviction via Opus;
   daemon reads and executes. Don't reach around the contract.
3. **Coin name normalization.** xyz clearinghouse returns `xyz:BRENTOIL`,
   native returns `BTC`. Always handle both forms. This bug recurs — see
   `_coin_matches()` helper.
4. **LONG or NEUTRAL only on oil — except inside `oil_botpattern` subsystem**,
   which has dual kill switches (`enabled` + `short_legs_enabled`) both OFF
   by default. Outside that one subsystem the rule is absolute.
5. **Every position MUST have SL + TP on exchange.** No exceptions. Stops are
   ATR-based; TPs from thesis or 5×ATR default.
6. **Always add specific files to git — never `git add -A` or `git add .`**.
   Personal data (.env, keys, wallet addresses) must never enter git history.
7. **Slash commands are FIXED CODE.** Pure deterministic logic. Anything that
   touches AI or AI-derived content (thesis narratives, generated catalysts)
   MUST carry the `ai` suffix: `/briefai`, `/oilbotreviewai`. No exceptions.

---

## Versioning of This File

MASTER_PLAN.md describes **current reality and forward direction**. It is the
*living* plan. When reality shifts meaningfully — a phase completes, a major
workstream pivots, the vision changes — this file is **rewritten fresh** and
the previous version is **archived** to `docs/plans/archive/` with the naming
convention:

```
docs/plans/archive/MASTER_PLAN_YYYY-MM-DD_<slug>.md
```

Where `<slug>` is a short kebab-case description of the moment being
snapshotted (`pre-realignment`, `phase-3-shipped`, `multi-market-pivot`,
etc.). Archived snapshots are **append-only** — once filed, they are never
edited. They exist so you can read the stale version that motivated the
rewrite and trace how the plan evolved.

**The archive captures intent at a moment.** The build-log captures
incremental changes. MASTER_PLAN.md captures *now*. All three together let
you reconstruct any past state of the project.

> Past versions: see `docs/plans/archive/` (oldest first by filename sort).
