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
| **Tradeable thesis markets** | BTC, BRENTOIL, GOLD, SILVER. **Active edge: oil + BTC.** GOLD + SILVER theses stale since early April — conviction engine auto-clamps (safe). WTI (CL) + SP500 added to `markets.yaml` but no thesis files yet. |
| **Multi-market config** | `data/config/markets.yaml` + `common/markets.py` `MarketRegistry` |
| **Agent runtime** | Embedded Claude Code port, session-token auth, no API keys. Agent tools extracted to `cli/agent_tools.py` (READ auto-exec, WRITE with approval, DISPLAY bypass LLM). Continuous typing indicator. |
| **Test suite** | Green. Run: `cd agent-cli && .venv/bin/python -m pytest tests/ -q` |
| **Daemon iterators** | See `cli/daemon/iterators/` and `cli/daemon/tiers.py` |
| **Telegram commands** | See `def cmd_*` in `cli/telegram_bot.py` and `cli/telegram_commands/*.py` |
| **Memory.db backups** | Hourly atomic snapshots in `data/memory/backups/` (24h/7d/4w retention) |
| **Lesson corpus** | Wired end-to-end; awaiting first real closed trade |
| **Oil Bot Pattern System** | Sub-systems 1-5 SHIPPED, sub-system 6 L1+L2 SHIPPED — kill switches OFF on the trading paths |
| **News → Thesis Pipeline** | thesis_challenger (mechanical) + thesis_updater (Haiku-powered) — both shipped 2026-04-10, registered all tiers |
| **Self-improvement engines** | Context Engine, Lab Engine, Architect Engine — shipped 2026-04-10, kill switches OFF |
| **Mission Control** | FastAPI (:8420) + Next.js 15 (:3000) + Astro Starlight docs (:4321) — local web dashboard, shipped 2026-04-10 |
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
`thesis_updater` (Haiku-powered news → conviction adjustment — default
disabled, manually enabled per `f622708`),
`lab` (strategy development pipeline), `architect` (mechanical self-improvement).

---

## Active Workstreams

### 1. System-Wide Hardening (shipped 2026-04-10, continued 2026-04-11)

20+ commits covering infrastructure, reliability, and correctness:

- **Shared account state** — unified native + xyz + spot USDC equity
  across all surfaces (daemon, CLI, heartbeat, daily report, risk monitor)
- **Atomic state persistence** — all daemon state writes use atomic
  rename-into-place
- **Durable pending approvals** — survive bot restarts
- **Telegram hardening** — polling resilience, error messages, input flow
- **Oil botpattern** — account-wide risk gate (COOLDOWN/CLOSED blocks
  entries), total_equity instead of native-only
- **Market structure** — 1m candle cache for oil classifier
- **Plain-English daemon alerts** — all Telegram messages rewritten
- **Agent harness rewrite** — tool definitions extracted to `cli/agent_tools.py`,
  trade evaluator to `cli/trade_evaluator.py`, continuous typing indicator,
  DISPLAY_TOOLS (calendar/research/technicals) bypass LLM commentary,
  calendar alerts auto-injected into agent context
- **Live chart candles** — 3s tick endpoint (`/charts/candles/{coin}/tick`),
  `series.update()` for real-time candle movement without full redraw

### 2. News → Thesis Pipeline (shipped 2026-04-10)

Closes the gap where news headlines were collected but never updated
thesis conviction. Two new iterators:

- **thesis_challenger** — pure Python, zero LLM. Pattern-matches catalysts
  against thesis `invalidation_conditions`. Default enabled.
- **thesis_updater** — Haiku-powered catalyst classification (0-10 impact).
  Direction-aware tiered response: CRITICAL = instant defensive mode,
  MAJOR/MODERATE = conviction delta with guardrails (±0.15/event,
  ±0.30/24h, direction never flipped). Audit trail: `data/thesis/audit.jsonl`.
  Default disabled.

**Remaining:** Telegram commands `/newslog`, `/audittrail`, `/overrule`.
Full article deep-fetch (pass 2) rate limited to 5/hour.

### 3. Self-Improvement Engines (shipped 2026-04-10)

- **Context Engine** (`modules/context_engine.py`) — classifies Telegram
  message intent, pre-fetches relevant data before LLM sees the question.
  **Not yet wired to Telegram agent.**
- **Lab Engine** (`modules/lab_engine.py`) — strategy development pipeline.
  **Needs backtest harness integration.**
- **Architect Engine** (`modules/architect_engine.py`) — reads autoresearch
  evaluations, detects patterns, proposes config changes. **Needs Telegram
  approval flow (`/architect approve <id>`).**

### 4. Mission Control Web Dashboard (shipped 2026-04-10)

Full local web UI for the trading system:

- **FastAPI backend** (:8420) — see `web/api/routers/` for current routers
- **Next.js 15 dashboard** (:3000) — Dashboard (equity curve, positions,
  health, iterators, thesis cards, news feed), Charts (candlestick +
  Bollinger + SMA/EMA), Control (kill switches, config editor, authority),
  Thesis Editor, Logs (SSE streaming), Strategies, Alerts
- **Astro Starlight docs** (:4321) — searchable docs site
- **macOS launcher** — `scripts/Mission Control.app` double-click launcher

**Remaining:** Real-time WebSocket push (currently polling). Authentication
for remote access (currently localhost-only). Mobile-responsive refinement.

### 5. Oil Bot Pattern — Sub-system 6 Final Wedges

Sub-systems 1-5 shipped. Sub-system 6 L1 (bounded auto-tune) + L2 (reflect
proposals) shipped. Remaining: L3 (pattern library growth) + L4 (shadow
trading harness). L5 (ML overlay) deferred until ≥100 closed trades.

**Specs**: `docs/plans/OIL_BOT_PATTERN_SYSTEM.md`, `OIL_BOT_PATTERN_06_SELF_TUNE_HARNESS.md`.

### 6. Multi-Market Expansion (Wedge 1 done)

`data/config/markets.yaml` + `common/markets.py` `MarketRegistry` shipped.
WTI + SP500 added to yaml. Five wedges remaining: thesis schema, catalyst
dictionary per asset class, auto-watchlist promotion, cascade strategy
generalization, doc reconciliation.

**Spec**: `docs/plans/MULTI_MARKET_EXPANSION_PLAN.md`.

### 7. Brutal Review Loop (Wedge 1 done)

`/brutalreviewai` command shipped. Wedges 2-6 remain: scheduled weekly
cadence, action queue parser, decision-quality grading, brutal top-5
validation.

**Spec**: `docs/plans/BRUTAL_REVIEW_LOOP.md`.

### 8. ADR-011 Two-App Quant Architecture (proposed, gated)

NautilusTrader-inspired sibling app (`quant/` alongside `agent-cli/`).
Gated on Tier 1 wins shipping first.

**Spec**: `docs/wiki/decisions/011-two-app-architecture-research-sibling.md`.

---

## Parked Plans (considered, deferred, may resume)

### Knowledge Graph Thinking Regime (parked 2026-04-09)

InfraNodus-inspired meta-cognitive layer. Cheaper alternative (markdown
checklist in `AGENT.md`) deployed instead.

**Resume condition**: a specific reasoning failure in production that the
markdown checklist fails to fix.
**Spec**: `docs/plans/KNOWLEDGE_GRAPH_THINKING.md`.

---

## Open Questions / Known Gaps

> Things known to be true at HEAD that need attention.

- **SILVER + GOLD theses are stale.** Conviction auto-clamped (safe), but
  not being traded. Either refresh or formally park.
- **WTI + SP500 in markets.yaml but no thesis files.** Added `f622708`
  but no `data/thesis/` JSONs exist yet. They'll be watchlist-only until
  theses are authored.
- **Context Engine partially wired.** Calendar alerts + DISPLAY_TOOLS
  (get_calendar, get_research, get_technicals) now in agent context.
  Full intent-classification pre-fetch loop not yet active.
- **Dream consolidation marks complete but doesn't call agent tools.**
- **`telegram_bot.py` is large.** Incremental extraction to
  `cli/telegram_commands/` submodules continues.
- **No real closed trade has flowed through the lesson layer yet.**
- **`data/snapshots/` grows unbounded.** No rotation strategy.
- **`chat_history.jsonl.bak` root cause not identified.** Workaround
  (read-union) in place.
- **Nothing in Oil Bot Pattern sub-systems 1-6 has had a real closed
  trade flow through.** Promotion blocked on live experience.
- **Mission Control is localhost-only.** No auth for remote access.
- **Thesis updater was manually enabled** (`f622708`) but its default
  config is `disabled`. Verify it's running correctly in production before
  relying on it.

---

## Package Map

| Package | CLAUDE.md | Wiki |
|---------|-----------|------|
| `common/` | `common/CLAUDE.md` | [wiki/architecture/current.md](../wiki/architecture/current.md) |
| `cli/` | `cli/CLAUDE.md` | [wiki/components/telegram-bot.md](../wiki/components/telegram-bot.md) |
| `cli/daemon/` | `cli/daemon/CLAUDE.md` | [wiki/components/daemon.md](../wiki/components/daemon.md) |
| `cli/telegram_commands/` | (per-submodule docstring) | (refactor in progress) |
| `modules/` | `modules/CLAUDE.md` | [wiki/components/conviction-engine.md](../wiki/components/conviction-engine.md) |
| `parent/` | `parent/CLAUDE.md` | [wiki/components/risk-manager.md](../wiki/components/risk-manager.md) |
| `agent/` | `agent/AGENT.md` + `SOUL.md` | [wiki/components/ai-agent.md](../wiki/components/ai-agent.md) |
| `guardian/` | (uses `guide.md`) | [wiki/components/guardian.md](../wiki/components/guardian.md) |
| `web/` | `web/CLAUDE.md` | (new — wiki page needed) |

---

## Session Workflow

```
1. Read NORTH_STAR.md + this file + relevant package CLAUDE.md
2. Read git history (cd agent-cli && git log --since="14 days ago" --oneline)
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
   native returns `BTC`. Always handle both forms. See `_coin_matches()`
   and `common/markets.py` MarketRegistry.
4. **LONG or NEUTRAL only on oil — except inside `oil_botpattern`
   subsystem**, which has dual kill switches both OFF by default. Enforced
   by `MarketRegistry.is_direction_allowed()`.
5. **Every position MUST have SL + TP on exchange.** No exceptions.
6. **Always add specific files to git — never `git add -A` or `git add .`.**
7. **Slash commands are FIXED CODE.** AI-dependent commands MUST carry
   the `ai` suffix. No exceptions.
8. **Authority is per-asset, parameterized, reversible.** Default `manual`.
9. **Append-only forever.** `chat_history.jsonl`, `feedback.jsonl`,
   `todos.jsonl`, `journal.jsonl`, lesson corpus, news catalysts — rows
   never deleted. State changes are new event rows.
10. **Read git history before claiming something doesn't exist.**
11. **Preserve everything, retrieve sparingly, bound every read path.**
    Per NORTH_STAR P10.

---

## Versioning of this file

MASTER_PLAN.md describes **current reality and forward direction**. When
reality drifts meaningfully, this file is **rewritten fresh** and the
previous version is **archived** to `docs/plans/archive/`.

> Past versions: see `docs/plans/archive/` (oldest first by filename sort).
