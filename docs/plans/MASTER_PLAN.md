# HyperLiquid Trading System — Master Plan

> **Read this + the relevant package `CLAUDE.md` at the start of every session.**
> **Vision:** `docs/plans/NORTH_STAR.md` (mandatory before any strategy/scope work)
> **System knowledge:** `docs/wiki/` · **Build history:** `docs/wiki/build-log.md`
> **Past plans:** `docs/plans/archive/` (append-only snapshots)

---

## What this system is

A personal trading instrument for one petroleum engineer (Chris) that
trades **with the dumb-bot reality** — anticipating obvious moves, fading
bot overshoot — instead of betting on the market being a fair discounting
mechanism. The user has the ideas. The system has the discipline. Markets
are 80% bots reacting to current news; the system turns Chris's
petroleum-engineering edge into structured signals the bots cannot read.

**Read `NORTH_STAR.md` for the founding insight, the L0–L5 self-improvement
contract, the authority model, and the historical-oracles vision.**

---

## Current Reality (always reflects HEAD)

| | |
|---|---|
| **Production tier** | WATCH (mainnet, launchd-managed) |
| **Authority model** | Per-asset via `common/authority.py` (`agent` / `manual` / `off`); default `manual`; persisted in `data/authority.json` |
| **Tradeable thesis markets** | BTC, BRENTOIL, GOLD, SILVER. **Active edge: oil + BTC.** GOLD + SILVER theses have been stale since early April — conviction engine auto-clamps them (safe), not being traded. Refresh or formally park. |
| **Multi-market config** | `data/config/markets.yaml` + `common/markets.py` `MarketRegistry` (Wedge 1 shipped 2026-04-09) |
| **Agent runtime** | Embedded Claude Code port, session-token auth, no API keys |
| **Test suite** | Green. Count: `cd agent-cli && .venv/bin/python -m pytest tests/ guardian/tests/ -q --collect-only 2>&1 \| tail -1`. Run: `cd agent-cli && .venv/bin/python -m pytest tests/ guardian/tests/ -q` |
| **Daemon iterators** | See `cli/daemon/iterators/` and `cli/daemon/tiers.py` |
| **Telegram commands** | See `def cmd_*` in `cli/telegram_bot.py` and `cli/telegram_commands/*.py` |
| **Memory.db backups** | Hourly atomic snapshots in `data/memory/backups/` (24h/7d/4w retention) |
| **Lesson corpus** | Wired end-to-end (verified 2026-04-09); 1 synthetic row marked rejected; awaiting first real closed trade |
| **Oil Bot Pattern System** | Sub-systems 1-5 SHIPPED, sub-system 6 L1+L2 SHIPPED — kill switches OFF on the trading paths |
| **News → Thesis Pipeline** | thesis_challenger (mechanical invalidation alerts) + thesis_updater (Haiku-powered conviction adjustment) — both kill switches OFF at ship. See workstream 6. |
| **Self-improvement engines** | Context Engine (intent-based pre-fetch), Lab Engine (strategy dev pipeline), Architect Engine (mechanical issue detection) — all kill switches OFF at ship. See workstream 7. |
| **Historical oracles** | `chat_history.jsonl`, `feedback.jsonl`, `journal.jsonl`, lesson corpus, news catalysts, supply ledger, thesis audit trail — all append-only forever per NORTH_STAR P9 |

**What's running on real money right now**: heartbeat dip-add / trim
against thesis files in `data/thesis/`, mandatory exchange-side SL+TP
enforcement, liquidation cushion monitor, auto-watchlist tracking of any
open position, lesson corpus retrieval injecting top-5 past lessons into
every agent decision, entry critic auto-grading every new position.
**WATCH tier — autonomous trade placement is gated on per-asset `agent`
delegation AND tier promotion to REBALANCE/OPPORTUNISTIC.**

**What's parked behind kill switches** (registered, tested, INERT until
manually flipped): `oil_botpattern` strategy engine (the only legal short
path on oil), `oil_botpattern_tune` and `oil_botpattern_reflect` (sub-system
6 self-improvement L1+L2), news_ingest dry-run severity floor,
`thesis_updater` (Haiku-powered news → conviction adjustment),
`lab` (strategy development pipeline), `architect` (mechanical self-improvement).

---

## Active Workstreams

### 1. 2026-04-09 Realignment Burst (in flight, this session)

The 2026-04-09 morning vision rewrite missed the founding philosophy, the
authority model, and the L0–L5 contract. The user flagged the gap with
critical feedback. This session is the corrective burst:

- ✅ NORTH_STAR.md rewritten against the founding insight
- ✅ MASTER_PLAN.md rewritten to match
- ✅ Both pre-realignment versions archived to `docs/plans/archive/`
- ✅ User-action queue iterator shipped
- ✅ Entry critic end-to-end verification shipped
- ✅ Chat history rotation audit + market-state correlation shipped
- ✅ `/feedback` + `/todo` hardening with append-only event semantics shipped
- ✅ Knowledge Graph Thinking Regime plan authored and PARKED (Wedge 1 YAML preserved on disk, not wired) — see "Parked Plans" below
- ✅ Oil Short Decision Checklist experiment added to `agent/AGENT.md` as the cheap alternative to the parked Knowledge Graph (2026-04-09 commit `d47a8f3`)
- ✅ Sub-system 5 activation runbook shipped (`docs/wiki/operations/` + `/activate` walkthrough command)
- ✅ Adaptive evaluator exit-only v1 wired into shadow-mode iterator (`72b9e90`, `f490c0f`, `165b0fe`)
- ✅ New Telegram commands: `/sim`, `/readiness`, `/activate`, `/adaptlog`, `/shadoweval` (sub-system 5 + L4 surfaces)
- ✅ Readiness thesis epoch-ms fallback + heatmap `snapshot_at` field fix (`9153805`)
- ✅ Bot classifier now fetches 1m candles from HL API directly (cache was empty) (`998b6bb`)
- ✅ Guardian meta-system DISABLED — all three hooks gutted, settings.json emptied, post-mortem in memory (`a9cc94e`, 2026-04-09 PM)
- ✅ `SYSTEM_REVIEW_HARDENING_PLAN.md` landed as the map for this review session

### 2. Oil Bot Pattern System — Sub-system 6 final wedges

Sub-systems 1-5 shipped. Sub-system 6 L1 (bounded auto-tune) + L2 (reflect
proposals) shipped 2026-04-09. Remaining: L3 (pattern library growth) +
L4 (shadow trading harness). L5 (ML overlay) deferred until ≥100 closed
trades exist.

**Specs**: `docs/plans/OIL_BOT_PATTERN_SYSTEM.md`, `OIL_BOT_PATTERN_06_SELF_TUNE_HARNESS.md`.

### 3. Multi-Market Expansion (Wedge 1 done)

`data/config/markets.yaml` + `common/markets.py` `MarketRegistry` shipped
in commit `0c7bebc` (2026-04-09). The hardcoded long-only-oil rule moved
from a static function check to a per-instrument config row. **Behavior
identical at ship time** — the oil long-only rule continues to be enforced
exactly as before, just via the registry instead of the hardcode.

**Spec**: `docs/plans/MULTI_MARKET_EXPANSION_PLAN.md`. Six wedges total;
five remaining (thesis schema, catalyst dictionary per asset class,
auto-watchlist promotion, cascade strategy generalization, doc reconciliation).

### 4. Brutal Review Loop (Wedge 1 done)

`/brutalreviewai` command + `BRUTAL_REVIEW_PROMPT.md` literal prompt
shipped in commit `52a258f` (2026-04-09). Wedges 2-6 remain: scheduled
weekly cadence, action queue parser, decision-quality grading, brutal
top-5 validation.

**Spec**: `docs/plans/BRUTAL_REVIEW_LOOP.md`.

### 6. News → Thesis Pipeline (shipped 2026-04-10, kill switches OFF)

Closes the gap where news headlines were collected but never updated
thesis conviction. Two new iterators, both registered all tiers:

- **thesis_challenger** — pure Python, zero LLM. Pattern-matches
  catalysts against thesis `invalidation_conditions`. Fires CRITICAL
  Telegram alert when a ceasefire headline matches "April 6 Trump
  deadline" at 90% confidence. Kill switch:
  `data/config/thesis_challenger.json` (default: enabled).
- **thesis_updater** — calls Haiku (cheap, fast) to classify each
  catalyst's impact (0-10). CRITICAL (9-10): instant defensive mode
  (Guard Phase 2, leverage halved) or conviction boost if news helps
  position. MODERATE/MAJOR: smaller conviction deltas with price
  confirmation upgrade. Guardrails: ±0.15/event, ±0.30/24h, direction
  NEVER flipped, weekend ×0.5 dampening. Audit trail:
  `data/thesis/audit.jsonl`. Kill switch: `data/config/thesis_updater.json`
  (default: disabled).

**Remaining:** Telegram commands `/newslog`, `/audittrail`, `/overrule`
for user review and override. Full article deep-fetch (pass 2) rate
limited to 5/hour.

### 7. Self-Improvement Engines (shipped 2026-04-10, kill switches OFF)

Three new engines to make the system learn and improve autonomously:

- **Context Engine** (`modules/context_engine.py`) — classifies Telegram
  message intent and pre-fetches relevant data (positions, thesis, trades,
  market state) BEFORE the LLM sees the question. The model doesn't choose
  what to look up — the data is put in front of it.
- **Lab Engine** (`modules/lab_engine.py`) — autonomous strategy
  development pipeline: discover → hypothesis → backtest → paper trade →
  graduated. Multiple strategies per market. CLI: `hl lab`.
- **Architect Engine** (`modules/architect_engine.py`) — reads autoresearch
  evaluations and detects recurring patterns. Proposes config changes for
  user approval. 12h cadence, zero LLM. CLI: `hl architect`.

**Remaining:** Wiring Context Engine into Telegram agent message handler.
Lab needs backtest harness integration. Architect needs Telegram approval
flow (`/architect approve <id>`).

### 8. ADR-011 Two-App Quant Architecture (proposed, gated)

The NautilusTrader-inspired sibling app (`quant/` alongside `agent-cli/`)
with Parquet data catalog. **Approved as ADR-011** (490 lines, status
`Proposed`, dated 2026-04-07). Gated on Tier 1 wins shipping first
(snapshot bleeding fix, daily report data-driven, Phase 3 REFLECT loop
wiring).

**Spec**: `docs/wiki/decisions/011-two-app-architecture-research-sibling.md`.

---

## Parked Plans (considered, deferred, may resume)

Plans that were authored but explicitly parked because the value case
is not strong enough to invest in implementation today. Each parked
plan has a documented **resume condition** in its plan doc — when that
condition is met, revisit. Until then, do not build.

### Knowledge Graph Thinking Regime (parked 2026-04-09 evening)

InfraNodus-inspired meta-cognitive layer above `agent/AGENT.md`. The
plan + Wedge 1 YAML files (concept catalog + oil_short_decision graph)
were shipped earlier in the same session, then immediately re-evaluated
when Chris pushed back: *"I don't think we've thought through the
knowledge graph concept... I want it evaluated for value."* The honest
evaluation found that none of the three claimed problems are
user-reported failures, and a markdown checklist in `AGENT.md` would
be a much cheaper test of the same hypothesis. Wedge 2 was NOT built.

**Spec**: `docs/plans/KNOWLEDGE_GRAPH_THINKING.md` (status: PARKED).
**On-disk artifacts** (preserved, not wired): `docs/plans/thinking_graphs/_concepts.yaml`, `docs/plans/thinking_graphs/oil_short_decision.yaml`.
**Resume condition**: a specific reasoning failure observed in production
that a markdown checklist in `AGENT.md` fails to fix.

---

## Open Questions / Known Gaps

> Things known to be true at HEAD that need attention. Updated when reality
> changes — don't let this section rot. If you fix one, cross it out and
> add a build-log entry explaining what shipped.

- **SILVER + GOLD theses are stale.** Conviction auto-clamped (safe), but
  the system isn't trading those markets. Either refresh them or formally
  park them.
- **Streaming agent output is built but not wired to Telegram.** UX
  paper-cut. Agent thinks for 30+ seconds and the user sees nothing until done.
- **Dream consolidation marks complete but does not call agent tools.**
  Memory consolidation works; tool-using consolidation does not.
- **Vault BTC excluded from `_fetch_account_state_for_harness()`.** Vault
  rebalancer manages it independently — minor visibility gap.
- **`telegram_bot.py` is ~4,400 lines** after Wedge 1 (-220 LOC for
  lessons extraction) + Wedge 2 (portfolio commands extraction, commit
  `4ffc805`). Working. Should continue incrementally splitting into
  `cli/telegram_commands/` submodules. Wedges 3-7 remain.
- **No real closed trade has flowed through the lesson layer yet.** The
  pipeline is verified end-to-end on a synthetic row (smoke test agent,
  lesson #47 marked rejected). The first real trade is a one-button
  follow-up by Chris.
- **`data/snapshots/` grows unbounded.** Flagged in ADR-011 §1 as Tier 1
  fix prerequisite. No rotation, no archival, no truncation strategy.
- **`chat_history.jsonl.bak` files are now read-unioned into search**
  (commit `1bc40c4`) and treated as historical oracle per NORTH_STAR P9.
  Root cause of the rotation/truncation that creates them is still not
  identified — audit closed with a workaround, not a fix.
- **Nothing in the Oil Bot Pattern sub-systems 1-6 has flowed through a
  real closed trade yet.** L1/L2/L3/L4 all depend on trade outcomes that
  haven't happened. Promotion is blocked on live experience, not code.
  See `BATTLE_TEST_LEDGER.md` (Phase B of this review) for the full
  classification.

---

## Package Map

| Package | CLAUDE.md | Wiki |
|---------|-----------|------|
| `common/` | `common/CLAUDE.md` | [wiki/architecture/current.md](../wiki/architecture/current.md) |
| `cli/` | `cli/CLAUDE.md` | [wiki/components/telegram-bot.md](../wiki/components/telegram-bot.md) |
| `cli/daemon/` | `cli/daemon/CLAUDE.md` | [wiki/components/daemon.md](../wiki/components/daemon.md) |
| `cli/telegram_commands/` | (per-submodule docstring) | (refactor in progress per Wedge 1) |
| `modules/` | `modules/CLAUDE.md` | [wiki/components/conviction-engine.md](../wiki/components/conviction-engine.md) |
| `parent/` | `parent/CLAUDE.md` | [wiki/components/risk-manager.md](../wiki/components/risk-manager.md) |
| `agent/` | `agent/AGENT.md` + `SOUL.md` | [wiki/components/ai-agent.md](../wiki/components/ai-agent.md) |
| `guardian/` | (uses `guide.md`) | [wiki/components/guardian.md](../wiki/components/guardian.md) |

---

## Session Workflow

```
1. Read NORTH_STAR.md + this file + relevant package CLAUDE.md
2. Read git history (cd agent-cli && git log --since="14 days ago" --oneline)
   — non-negotiable. The 2026-04-09 morning rewrite skipped this and
   produced a stale NORTH_STAR. Don't repeat the mistake.
3. Run /alignment to surface drift before doing anything
4. Browse docs/wiki/ for deeper context as needed
5. Do the work: TodoWrite for >3 steps, tests for new code, commit per
   logical unit
6. If architecture changed: update the wiki page (not this file)
7. If MASTER_PLAN itself drifts from reality: archive + rewrite (see
   MAINTAINING.md "Versioning convention")
8. Run /alignment again at end of session
```

---

## Critical Rules

1. **NEVER touch `~/.openclaw/`** — Chris's entire AI agent ecosystem
   lives there.
2. **Thesis files are the shared contract.** Chris writes conviction via
   Opus; daemon reads and executes. Don't reach around the contract.
3. **Coin name normalization.** xyz clearinghouse returns `xyz:BRENTOIL`,
   native returns `BTC`. Always handle both forms. This bug recurs — see
   `_coin_matches()` helper and `common/markets.py` MarketRegistry
   normalization.
4. **LONG or NEUTRAL only on oil — except inside `oil_botpattern`
   subsystem**, which has dual kill switches (`enabled` +
   `short_legs_enabled`) both OFF by default. The rule is enforced by
   `MarketRegistry.is_direction_allowed()` reading
   `data/config/markets.yaml`. Outside the exception subsystem the rule
   is absolute.
5. **Every position MUST have SL + TP on exchange.** No exceptions. Stops
   are ATR-based; TPs from thesis or 5×ATR default.
6. **Always add specific files to git — never `git add -A` or `git add .`.**
   Personal data (.env, keys, wallet addresses) must never enter git history.
7. **Slash commands are FIXED CODE.** Pure deterministic logic. Anything
   that touches AI or AI-derived content (thesis narratives, generated
   catalysts) MUST carry the `ai` suffix: `/briefai`, `/oilbotreviewai`,
   `/lessonauthorai`, `/brutalreviewai`. No exceptions.
8. **Authority is per-asset, parameterized, reversible.** The bot is not
   always supervised. The user can set any asset to `agent` (bot trades
   it autonomously), `manual` (bot is safety net only), or `off` (no
   monitoring). The default is `manual`. Per NORTH_STAR P6 (delegated
   autonomy, not constant supervision).
9. **Append-only forever.** `chat_history.jsonl`, `feedback.jsonl`,
   `todos.jsonl`, `journal.jsonl`, lesson corpus, news catalysts — none
   of these get rows deleted, ever. State changes are NEW append-only
   event rows that reference the original by id. Per NORTH_STAR P9 (historical
   oracles).
10. **Read git history before claiming something doesn't exist.** Per
    NORTH_STAR P2. Two sessions in two days lost time to this — don't
    make it three.
11. **Preserve everything, retrieve sparingly, bound every read path.**
    Per NORTH_STAR P10. Rule 9 (append-only forever) and Rule 11 are
    a pair: the corpus grows without limit, the working set per
    decision does not. Every code path that reads from a historical
    store and feeds the result into an agent prompt, a Telegram message,
    or a tool result MUST have a hard upper cap (parameter default +
    hardcoded ceiling that clamps user input). The failure mode is
    silent and asymmetric — an unbounded read that returns 21 rows
    today returns 21,000 rows in three years. See NORTH_STAR P10 for
    the per-surface retrieval contract table.

---

## Versioning of this file

MASTER_PLAN.md describes **current reality and forward direction**. It is
the *living* plan. When reality drifts meaningfully — a phase completes,
a workstream pivots, the vision changes — this file is **rewritten fresh**
and the previous version is **archived** to `docs/plans/archive/` with
the naming convention:

```
docs/plans/archive/MASTER_PLAN_YYYY-MM-DD_<slug>.md
```

Where `<slug>` is a short kebab-case description of the moment being
snapshotted. Archived snapshots are append-only — never edited. They
exist so future sessions can read the stale version that motivated the
rewrite and trace how the plan evolved.

**The archive captures intent at a moment.** The build-log captures
incremental change. MASTER_PLAN.md captures *now*. NORTH_STAR.md
captures the vision. All four reconstruct any past state of the project.

> Past versions: see `docs/plans/archive/` (oldest first by filename
> sort). The 2026-04-09 morning version (`MASTER_PLAN_2026-04-09_pre-philosophy-realignment.md`)
> is the most recent — read its archival header for the lesson.
