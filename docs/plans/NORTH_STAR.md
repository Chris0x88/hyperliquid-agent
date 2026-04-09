# NORTH STAR

> The single document that says **what we are building, why, and what good looks like**.
> Read this before any session that touches strategy, scope, or vision.
> Past versions: see `docs/plans/archive/NORTH_STAR_*.md` (append-only snapshots).

---

## The founding insight

> *Markets are dumb. ~80% of trades are bots reacting to known information,
> not forecasting. Ahead of major scheduled catalysts (e.g. Trump's 8 PM Iran
> deadline), oil drifted up to the minute, then violently over-corrected ~20%
> on the no-deal-yet-then-deal pattern, despite Russian/Iranian refinery damage
> and Middle East supply disruptions remaining offline.*
>
> *A petroleum engineer trying to forecast the fundamental gets killed by bots
> that don't read the supply ledger. **The arbitrage: be early on the obvious
> thing, then fade the bot overcorrection when it lands.***
>
> — Chris, 2026-04-09. The triggering observation that defined the entire
> active workstream. Source: `docs/plans/OIL_BOT_PATTERN_SYSTEM.md` §1.

This is the project's reason to exist. Every other principle below cascades
from it. The market is no longer a discounting mechanism. It is a slow
overreaction machine driven by bots that react to events as they land, not
ahead of them. The user is a petroleum engineer with real fundamental edge
on oil supply. **That edge is worthless if it gets steamrolled by bots that
don't read it.** So the system trades *with* the bot reality — anticipating
the obvious move, then fading the overshoot — instead of betting on
fundamentals being respected by counterparties who don't read fundamentals.

This insight was not in the previous NORTH_STAR. The previous NORTH_STAR
was archived precisely because it missed this. Read
`docs/plans/archive/NORTH_STAR_2026-04-09_pre-philosophy-realignment.md` for
the contrast and the lesson.

---

## What this system is

A **personal trading instrument** for one petroleum engineer, evolving toward
a **multi-market discipline-execution platform** that:

1. **Captures** Chris's ideas the moment he has them, with zero friction
2. **Encodes** his domain edge (oil now, all HL markets eventually) as
   structured data the bots cannot read but the system can
3. **Trades** that edge using the dumb-bot reality (anticipate obvious moves,
   fade overshoot) rather than betting against it
4. **Protects** real capital with mandatory exchange-side stops, drawdown
   circuit breakers, and a per-asset autonomy ladder
5. **Learns** from every closed trade, every conversation, every catalyst,
   storing the corpus as historical oracles forever
6. **Improves itself** within bounded parameters, but never changes its
   own structure without one human tap

The user has the ideas. The system has the discipline. The system trades
the bot reality. **The system never bets on the market being smart.**

---

## The Five Promises

The system makes five promises and is judged against each.

### 1. Capture every idea before it evaporates
Telegram is the catch surface today. Voice + screenshot + multi-interface
capture is the roadmap. When Chris has a thought at 11pm, it must become
structured input the system understands inside 60 seconds, without opening
a laptop.

### 2. Encode petroleum-engineering edge as data the bots can't read
The supply disruption ledger, the bot-pattern classifier, the heatmap, the
catalyst ingestion — all of these exist to convert Chris's domain knowledge
into structured signals the system can act on. The dumb bots are not
reading them. That asymmetry IS the edge.

### 3. Trade with the bot reality, not against it
Forecasting is dead as a thesis defense. Every position the system opens
asks "what are the bots about to do" first, then "is the fundamental
correct" second. Long-horizon thesis positions live in the existing
conviction engine path. Tactical positions exploiting bot overshoot live
in the `oil_botpattern` strategy engine path with a hard 24h cap on
shorts. Two writers, one shared safety net (mandatory SL+TP).

### 4. Learn from everything, forget nothing
Every closed trade → lesson. Every Telegram message → chat history (NEVER
deleted). Every `/feedback` entry → append-only event log (NEVER deleted).
Every `/todo` → same. Every catalyst → news ledger. Every supply event →
disruption ledger. Going forward, every chat row will also record market
state at the moment (price, equity, positions) so the corpus becomes a
**timestamped historical oracle** — the most valuable data the system has.

### 5. Improve within bounds, never restructure without permission
The L0–L5 self-improvement contract from `OIL_BOT_PATTERN_SYSTEM.md` §6
is non-negotiable: the system is allowed to LEARN automatically (auto-tune
parameters, grow the lesson corpus, refine catalyst rules) but is NOT
allowed to CHANGE STRUCTURE (new strategies, new sub-systems, new gates)
without one human tap. **Crossing that line is how trading systems blow
up overnight.**

---

## What this project is NOT

A clear no-list to prevent scope creep:

- **NOT** a forecasting system. We do not predict where the market should
  go and bet on it being right. The market is not a forecasting tool
  anymore — it's a slow overreaction machine.
- **NOT** an "always human in the loop" bot. The handoff system in
  `common/authority.py` lets Chris set per-asset authority to `agent`,
  `manual`, or `off`. The WATCH/REBALANCE/OPPORTUNISTIC tier ladder is the
  system-wide autonomy dial. The default is safe (`manual`), but the
  system CAN run autonomously on delegated assets.
- **NOT** a rebuild of hyperliquid.xyz. That platform is excellent for
  manual trading and watching. We do not duplicate it. The bot consumes
  HL data and posts decisions; the user uses hyperliquid.xyz directly when
  they want to look at charts manually.
- **NOT** a strategy marketplace, signal-sharing service, or anything
  user-facing beyond Chris.
- **NOT** a paper-trading sandbox. Real capital from day one. Mock mode
  exists for testing only.
- **NOT** dependent on any cloud LLM provider for trading decisions.
  Session-token auth means zero ongoing API cost for the agent. The
  trading core is pure Python and runs without an LLM at all.
- **NOT** free to evolve unchecked. Mandatory tests, mandatory backups,
  mandatory ADRs for architectural decisions. Discipline applies to the
  codebase the same way it applies to the trading.

---

## The Authority Model (per-asset, parameterized)

The single biggest correction from the previous NORTH_STAR. **The bot is
not always supervised.** The handoff system in `common/authority.py`
defines three per-asset levels:

| Level | What the bot can do | Where it lives |
|---|---|---|
| **`agent`** | Bot manages entries, exits, sizing, dip-adds, profit-takes. User gets reports. | `data/authority.json` per asset, set via `/delegate <ASSET>` |
| **`manual`** (default) | User trades. Bot is safety-net only — ensures SL/TP exist, alerts on dangerous leverage. Never enters or exits. | Default for any unregistered asset |
| **`off`** | Not watched at all. No alerts, no stops, nothing. | Set via `/authority <ASSET> off` |

Above the per-asset authority, there is the **system-wide tier ladder** in
`cli/daemon/tiers.py`:

| Tier | Iterators active | Bot behavior |
|---|---|---|
| **WATCH** (current production) | Read-only iterators only — no `execution_engine`, no `rebalancer`, no `oil_botpattern` | Reports + alerts only. Cannot place trades. |
| **REBALANCE** | All WATCH + `execution_engine`, `rebalancer`, `oil_botpattern`, `oil_botpattern_tune`, `oil_botpattern_reflect`, `catalyst_deleverage` | Trades on delegated assets only |
| **OPPORTUNISTIC** | All REBALANCE | Same as REBALANCE — full autonomy on delegated assets |

The promotion path is **explicit, reversible, per-asset, tier-gated, and
kill-switched**. Every risky subsystem ships with `enabled: false` by
default. Promotion requires deliberate action.

This is what "human in the loop" actually means in this codebase: the
human chooses which assets the bot owns, which tier the daemon runs in,
and which subsystems are enabled. After those choices are made, the bot
can operate autonomously on the scope it was granted. **It is a
*delegated* autonomy model, not a *supervised* one.**

---

## The L0–L5 Self-Improvement Contract

Verbatim from `OIL_BOT_PATTERN_SYSTEM.md` §6 — load-bearing across the
entire system, not just oil_botpattern:

| Layer | What it does | Cadence | Human in loop |
|---|---|---|---|
| **L0 — Hard contracts** | Tests fail before bad code ships. Verification before completion. SL+TP enforced. JSON schemas on every data file. | Per commit / per tick | None — automatic |
| **L1 — Bounded auto-tune** | Strategy params have hard min/max in YAML. Journal-replay nudges them within bounds after every closed trade. Audit-logged. | Per closed trade | None — automatic |
| **L2 — Reflect proposals** | Existing autoresearch reflect loop reads journal weekly, posts STRUCTURAL changes (new patterns, new bounds, new market) to Telegram. | Weekly digest | Chris — one tap promote/reject |
| **L3 — Pattern library growth** | Classifier auto-adds new bot-pattern signatures to versioned catalog. Catalog grows freely; live signal set requires one tap to promote. | Per new pattern | Chris — one tap |
| **L4 — Shadow trading** | Every L2/L3 proposal runs in shadow (paper) mode for ≥ N closed trades before being eligible for promotion. The system collects its own evidence. | Per proposal | None — automatic |
| **L5 — ML overlay (deferred)** | A small model on top of L4 evidence. **ONLY after ≥100 closed trades.** Until then: not implemented. Dumb-bot pattern detection is heuristic until the data justifies otherwise. | Deferred | Chris — model gating |

**The contract**: the system is allowed to LEARN automatically. The system
is not allowed to CHANGE STRUCTURE without one human tap. Crossing that
line is how trading systems blow up overnight.

L5 deserves emphasis: **we are wary of overfitting**. The data is too
sparse (low-hundreds of trades/year) for gradient learning to beat
classical heuristics with bounded auto-tune. ML may be added at L5 once
≥100 closed trades exist to train against; until then it is fairy dust.

---

## The Quant Data Architecture (ADR-011)

Approved planning: `docs/wiki/decisions/011-two-app-architecture-research-sibling.md`

The user explicitly asked for "a quant system that stores all the relevant
market data properly... based on NautilusTrader." That plan is **already
written** as ADR-011 (490 lines, status `Proposed`, dated 2026-04-07).

**Architecture summary:**
- New sibling app `quant/` alongside `agent-cli/` in the same repo
- NautilusTrader-style **Parquet data catalog** at `quant/catalog/`
  (Hive-partitioned by instrument / interval / year / month)
- Stores: candles, snapshots, fills, signals, features, predictions
- Bot keeps: execution, risk management, Telegram I/O
- Quant app owns: data ingestion, signal computation, backtesting, ML, reports
- Communication via file-based contract (Parquet signals + PDF reports)
- **Nautilus is the data + research engine. NOT the live execution engine.**
  The existing `parent/hl_proxy.py` continues to handle HyperLiquid I/O.
- Strategies migrate from autonomous traders to signal generators (Freqtrade-style)

**Why a sibling app, not embedding:** Nautilus is opinionated. Embedding
inside the existing daemon means fighting its `MessageBus` and `Actor`
model for ownership of the event loop. As a sibling app it is a joy. As a
guest it is a war. (ADR-011 §1.3)

**Status:** Proposed, awaiting Tier 1 completion gate per ADR-011 §8:
> Tier 1 wins ship before any new app is built. Snapshot bleeding fix,
> daily report made data-driven, and Phase 3 REFLECT loop wiring all
> happen first, on the existing bot, with zero dependency on the new app.
> This banks safe value before architectural risk.

**When to greenlit `quant/` build:** when Chris is ready to commit a
multi-week dedicated build cycle, the ADR is the entry point. Read ADR-011
end-to-end before starting.

---

## Historical Oracles — the data the system never deletes

The user said: *"All my chat history in telegram should be saved and be
able to be analysed... But never deleted... It's amazing historical data
and those historical oracles will literally become the most valuable
information we have, especially timestamped in context of where market was
at and where it subsequently went."*

**The vision**: every Telegram message, every `/feedback`, every `/todo`,
every closed trade, every catalyst, every supply disruption — all
timestamped, all enriched with market state at the moment, all append-only,
all forever, all searchable.

**What exists today:**

| Source | File | Status |
|---|---|---|
| Telegram chat | `data/daemon/chat_history.jsonl` | Append-only, 299+ rows. **Going forward**: market_context (price + equity + positions) added per row. |
| User feedback | `data/feedback.jsonl` | Append-only, 21+ rows since 2026-04-02. Status managed via append-only event rows (never edits the original). |
| User todos | `data/todos.jsonl` | Same pattern. |
| Closed trades | `data/research/journal.jsonl` | Append-only. Feeds the lesson layer. |
| Lessons (verbatim post-mortems) | `data/memory/memory.db` `lessons` table + FTS5 | Append-only. BM25 retrieval. Top-5 auto-injected into every agent decision. |
| News catalysts | `data/news/catalysts.jsonl` | Append-only. |
| Supply disruptions | `data/supply/state.json` + ledger files | Append-only. |
| Agent memory | `data/agent_memory/` | Append-only with rolling trim (the only file with rotation, and only for the agent's working set, not the corpus). |

**Critical rules**:
- NEVER delete rows from any of the above
- NEVER rotate-and-truncate; if archival is needed, copy to `*-YYYYMM.jsonl.archive` and KEEP the live file intact
- Every NEW row gets timestamped market state when it's cheap to gather
- The corpus is searchable (BM25 for lessons, substring for chat/feedback/todo today, FTS5 follow-up wedge for the latter)
- The corpus is referenced by the agent on every decision

**What shipped 2026-04-09 evening**: chat history market-state
correlation + `/chathistory` search (with `.bak` union per P10) +
`/feedback` and `/todo` hardening with append-only event semantics. The
rotation *audit* closed with a workaround (unioned `.bak` files into
search) rather than a fix — root cause of rotation/truncation is still
unknown and parked in MASTER_PLAN open questions.

---

## The User-Action Queue (the "I'll forget if you don't tell me" fix)

The user said: *"There are so many things you are relying on me to
trigger... We need something in the schedule that documents all this! And
prompts the user what tools to trigger! Otherwise I simply will forget and
not know.... The codebase will disintegrate if I don't know how to run
it..."*

**The fix**: a new daemon iterator that maintains a queue of "things Chris
should do" with cadence + last-done timestamps + Telegram nudges. Items
include:

- Memory.db restore drill (quarterly)
- `/brutalreviewai` weekly deep audit
- Thesis refresh check per market
- Lesson approval queue
- Backup health check
- `/alignment` ritual reminder (start + end of session)
- Unresolved feedback aging review

**Status**: SHIPPED 2026-04-09 as `cli/daemon/iterators/action_queue.py`
+ `/nudge` Telegram command + 5-surface registration. **The user no
longer has to remember which manual rituals are due — the system tells
them.** Battle-test status: synthetic-verified; first real nudge fire
pending (see `BATTLE_TEST_LEDGER.md` after Phase B of the review plan).

---

## The Knowledge Graph Thinking Regime — PARKED 2026-04-09

The user was inspired by **InfraNodus knowledge graphs** for thinking
regimes that guide LLMs in *how to think*, *how to learn*, what style
and considerations matter. A plan doc + Wedge 1 YAML files (concept
catalog + first decision graph) were authored and shipped earlier in
the same session.

**Status**: **PARKED** the same day. When asked to evaluate the value,
the honest answer was: none of the three claimed problems (flat
reasoning, implicit domain knowledge, missing thinking shape) are
user-reported failures. They were architectural aesthetics projected
onto the InfraNodus inspiration. A markdown checklist in `agent/AGENT.md`
would be a much cheaper test of the same hypothesis.

**Resume condition**: a specific reasoning failure observed in
production that a markdown checklist in `AGENT.md` fails to fix.

**On-disk artifacts** (preserved per CLAUDE.md "additive over destructive"):
- `docs/plans/KNOWLEDGE_GRAPH_THINKING.md` — plan doc with parking note
- `docs/plans/thinking_graphs/_concepts.yaml` — 23 concepts
- `docs/plans/thinking_graphs/oil_short_decision.yaml` — 18-node graph

These are NOT wired into any code path. Wedge 2 (the loader) was never
built and will not be built without explicit reauthorization.

**The lesson**: this entry stays in NORTH_STAR as a record of a
considered-and-deferred direction, and as a marker for the meta-lesson
captured in P5 below — *a feature that came up in passing in a
brainstorming feedback dump is NOT pre-validated*.

---

## The Multi-Interface Roadmap

Telegram is the primary interface today and will be for Horizon 1. Beyond
that:

**Today (Horizon 0):** Telegram bot. Hyperliquid.xyz for manual trading
and chart watching. Claude Code sessions for development.

**Horizon 1 (0-12 months):**
- Voice capture in Telegram for hands-free thesis input
- Screenshot OCR for chart sharing
- Web dashboard for *display* (not trading) — the bot stays as the
  trading authority; the web is read-only views into account state,
  lessons corpus, action queue, brutal review reports
- ⚠️ **EXPLICIT BOUNDARY**: never rebuild hyperliquid.xyz. That platform
  is the best in the space for manual trading and watching. The user uses
  it directly. We do not duplicate it.

**Horizon 2 (12-24 months):**
- The web dashboard becomes a real workspace for thesis editing, lesson
  review, and brutal review action triage
- A possible Mac menubar app for at-a-glance equity / position state
- The quant `quant/` sibling app from ADR-011 ships, with notebook-based
  research workflow

**Horizon 3 (24-36+ months):**
- Quietly excellent personal infrastructure
- Multi-instrument, multi-strategy, multi-timeframe
- Self-tuning within bounds, structurally stable, reviewable in one
  weekly session

---

## Operating Principles (the rules behind the rules)

These are the principles every architectural decision is checked against.

### P1 — Discipline is the product, not a constraint
Every protection (mandatory SL+TP, drawdown brakes, conviction clamps,
kill switches, the per-asset authority model, the tier ladder, the
L0–L5 contract) exists because Chris explicitly asked for it. Removing a
protection requires a stronger argument than "it's annoying." The
annoyance IS the value.

### P2 — Reality first, docs second
Code that runs is the truth. Docs that describe what the code USED to do
are worse than no docs at all. **Read git history before claiming
something doesn't exist.** The 2026-04-07 hardening session lost time
writing a 600-line ADR based on a stale picture; the 2026-04-09 morning
rewrote NORTH_STAR without reading `common/authority.py` and got most of
P6 wrong; the 2026-04-09 evening rewrote it again to fix that. Each
mistake costs a session. The Brutal Review Loop and Guardian drift
detection enforce reality-first checking, but the discipline starts
in the session: **read first, write second.**

### P3 — Local-first, no rent
Session-token auth, SQLite + JSONL + Parquet (when ADR-011 lands)
storage, launchd-managed daemons, no cloud services for trading
decisions. The system runs forever for free. The day it stops being
local-first is the day it starts costing money you don't see.

### P4 — Additive over destructive
When in doubt, disable rather than delete. Quarantine rather than
overwrite. Archive rather than rewrite-in-place. CLAUDE.md's "no
destructive overreach" rule exists for a reason. Append-only event logs
for `/feedback`, `/todo`, lessons, journal, chat history. State changes
are NEW events, never edits to old rows.

### P5 — Confirm before building, commit per logical unit
Plans are cheap; rewrites of working code are expensive. The 2026-04-09
sub-system 5 plan was rejected and rewritten in 2 minutes — saving 2
hours of code. The 2026-04-09 evening realignment session would have
been avoided if the morning session had read `common/authority.py`
before asserting. **State your plan in 3-5 bullets. Get a nod. Then
build.**

**Sub-rule (added 2026-04-09 evening, after the Knowledge Graph parking)**:
**A feature that came up in passing in a brainstorming feedback dump
is NOT pre-validated.** Treat it as a hypothesis to test, not a spec
to implement. Before authoring a plan doc or shipping code:
1. Identify the specific user-reported failure the feature would fix
2. Compare against the cheapest possible alternative (often a markdown
   note in an existing file)
3. State the resume condition explicitly: "I will build this if X
   happens" — and if you can't articulate X, you don't have a problem
4. If no specific failure exists yet, file the idea as "deferred,
   awaiting demonstrated need" instead of starting work

This sub-rule exists because in 24 hours I (Claude) made the same
mistake twice: rewrote NORTH_STAR.md without reading git history
(morning), then wrote a 250-line plan + shipped Wedge 1 YAML for the
Knowledge Graph Thinking Regime without evaluating value (afternoon).
Both were caught by Chris with one pointed message. Both stem from
treating "the user mentioned it once" as equivalent to "the user has
validated it as worth building." The Knowledge Graph plan is now
parked in MASTER_PLAN's "Parked Plans" section as the load-bearing
example of this failure mode.

### P6 — Delegated autonomy, not constant supervision
The bot is not always supervised. The bot can run autonomously on
delegated assets at REBALANCE or OPPORTUNISTIC tier. The human's
authority is in the *granting* of that scope (`/delegate`, tier
selection, kill switch flips), not in the moment-by-moment execution.
**The human chooses what the bot owns. The bot owns it.** The L0–L5
contract is what makes this safe: structural changes require a tap;
parameter tuning within bounds does not.

### P7 — Compound wealth via the dumb-bot reality
Per Chris's verbatim framing in build-log 2026-04-09 sub-system 5:
> Compound wealth as fast as possible (without tanking the account).
> Put me under pressure to perform and take risk to make big money when
> I have a high edge, and bet less money when my edge is small.

Combined with the founding insight at the top of this doc: aggressive
sizing on high-conviction setups that exploit dumb-bot patterns,
defensive sizing on low-conviction setups, **and never bet on the market
being smart enough to discount fundamentals correctly**. Drawdown brakes
are the floor that makes aggressive sizing safe. The 80% bot reality is
the input that makes "high conviction" mean "I see a bot pattern about
to land," not "I see an undervalued asset."

### P8 — Honest feedback over comfortable consensus
The system must be brutally honest in its self-reporting. A weekly
review that grades the codebase a C+ is more valuable than one that
grades it an A- to make Chris feel good. The Brutal Review Loop is the
formal mechanism for this; the spirit applies to every PR comment,
every wiki update, every alignment run, **every NORTH_STAR rewrite**.

### P9 — Historical oracles are forever
Append-only. Never delete. Every chat row, every feedback entry, every
trade, every catalyst, every supply event lives forever. The system
accumulates wealth-of-knowledge linearly with time. After 5 years, the
corpus IS the moat. Today's fix to stop chat history rotation is in
service of P9.

### P10 — Preserve everything, retrieve sparingly, bound every read path
**P9 says preserve forever. P10 says use sparingly.** The corpus is
allowed to grow to gigabytes. The working set per agent prompt or per
Telegram response is bounded. Every code path that reads from a
historical-oracle store and feeds the result into either (a) an agent
prompt, (b) a Telegram message, or (c) a tool result the agent will
see MUST have a hard upper cap. The cap may be a parameter default
*plus* a hardcoded ceiling that clamps user input — both, not either.

This rule exists because the failure mode is silent and asymmetric:
- An unbounded read path that returns 500 lessons one day will blow
  the agent's context window the next day with 5,000 lessons after
  the corpus grows.
- A `/feedback list` command that returns ALL entries today (21 rows)
  will return all 21,000 entries in 3 years.
- A chat history search that unions `.bak` files (followup 1) without
  a cap will return everything matching a common substring.

The retrieval contract per surface:

| Surface | Reaches | Default cap | Hard ceiling | Per-row truncation |
|---|---|---|---|---|
| Agent tool that returns rows (`search_lessons`, `get_feedback`) | Agent context window | 5-10 | 25 | Yes — body fields cap at ~3000 chars |
| Prompt injection section (`build_lessons_section`) | Agent system prompt | 5 | 5 | Yes — summary only, full body via separate tool |
| Telegram list commands (`/lessons`, `/feedback list`, `/chathistory`) | Telegram message | 10-15 | 25-50 | Yes — text fields cap at ~80-200 chars |
| Telegram detail commands (`/lesson <id>`, `/feedback show <id>`) | Telegram message | 1 row | 1 row | Yes — body cap at ~3000 chars to fit Telegram limit |
| Iterator alerts (entry critic, action queue) | Telegram message | 1 alert per detected event | N/A | Yes — message body bounded |

**The principle in one sentence**: data lives forever, but no single
read returns more than what fits cleanly in a Telegram message or in
the agent's context budget for one decision.

The 2026-04-09 late-evening realignment session shipped four new
historical-oracle surfaces (chat history correlation, `/chathistory`,
`/feedback list/search`, `/nudge`) and an audit was dispatched to
verify each one obeys this rule. Findings + minimal fixes were
applied in the integration commit. Future surfaces are required to
follow the contract above.

---

## What "startup-quality" means for this project

| Dimension | What good looks like | Current state |
|---|---|---|
| Test coverage | >90% on trade-touching code; deterministic tests for every gate | ✅ Living count via `pytest --collect-only` — ratio informally ~52% test:code at last measure |
| Backups | Hourly automated, integrity-checked, restore-drilled | ✅ memory.db hourly snapshots shipped 2026-04-09; restore drill runbook shipped same day; user-action queue (pending) will nudge quarterly drill |
| Audit trail | Every order, every decision, every reasoning step in append-only logs | ✅ Already in place — chat history, journal, lessons, feedback, todos all append-only (rotation audit underway) |
| Kill switches | Every subsystem has one. Default-off for risky things | ✅ Convention enforced — every iterator has a kill switch file in `data/config/` |
| Drawdown protection | Hard floors that auto-trigger | ✅ 3% daily / 8% weekly / 15% monthly in `oil_botpattern.json` |
| Documentation | Wiki + ADRs + build-log + plans + memory + archived snapshots | ✅ Living wiki, 14 ADRs, append-only build-log, plan archive convention |
| Drift detection | Continuous (Guardian) + periodic deep audit (Brutal Review Loop) | ⚠️ Guardian shipped then DISABLED 2026-04-09 (hook loop re-emitted stale narrative); `SYSTEM_REVIEW_HARDENING_PLAN.md` is the manual replacement. Brutal Review Loop wedge 1 shipped same day; never run yet. |
| Disaster recovery | Restore drill documented and run quarterly | ⚠️ Documented (`docs/wiki/operations/memory-restore-drill.md`); user-action queue shipped and will nudge for quarterly run. First real drill pending. |
| Observability | Metrics for funding cost, equity curve, win rate, lesson approval rate | ⚠️ Partial — needs the daily report from ADR-011 to be data-driven |
| Reproducibility | Mock mode for any iterator, replay harness for any past trade | ⚠️ Partial — mock mode exists; replay harness deferred to ADR-011 quant app |
| Security | Session token auth, dual-write secrets, no API keys | ✅ |
| Code review | Brutal review pass on every meaningful change | ⚠️ Brutal Review Loop wedge 1 (on-demand) shipped; weekly cadence pending wedge 3 |
| Versioned vision docs | Archive + rewrite, never silently mutate | ✅ Convention shipped 2026-04-09; THIS realignment is the second use of it |

---

## The Idea Funnel (revised for the dumb-bot reality)

How a Chris insight becomes a money-making position, in 5 stages:

```
   1. CAPTURE                    2. STRUCTURE                 3. SIZE
      ───────                       ─────────                   ─────
   Telegram /thesis              Encode as supply ledger     Conviction
   Voice memo (planned)          Encode as catalyst rule     0.0 → 1.0
   Screenshot (planned)          Encode as bot pattern       Druckenmiller
   /feedback (now)               Encode as thesis JSON       ladder

         ↓                            ↓                        ↓

   4. EXECUTE                                  5. LEARN
      ────────                                  ─────
   Two writers, one safety net:                Journal closes
   ┌─ thesis_engine path (long horizon)        Lesson candidate
   │  Druckenmiller conviction sizing          Dream cycle authors via Haiku
   │  Holds through corrections                FTS5 BM25 retrieval at next decision
   │                                           Approve/reject feedback loop
   └─ oil_botpattern path (tactical, ≤24h)
      Exploits bot overshoot                   Entry critic auto-fires per
      Hard 24h cap on shorts                   new position with deterministic
      Drawdown circuit breakers                grade + suggestions + lesson recall
      Both writers obey: SL+TP on exchange,
      authority check, tier check
```

The novel part vs the previous NORTH_STAR: **stage 3 is now informed by
the bot reality, not by forecasting confidence**. "High conviction" means
"I see a bot pattern about to land," not "I see a fundamental being
ignored." Stages 1, 2, 4, 5 are mature. Stage 3 needs the bot classifier
(sub-system 4, shipped) feeding the conviction band (in progress via
sub-system 6 self-tune harness, partially shipped).

---

## Direction-setting decisions already made

Pinned here so they don't need to be re-litigated:

- **Markets**: BTC + oil first, expand to all HL via config (Multi-Market
  Wedge 1 shipped 2026-04-09 — `data/config/markets.yaml` + MarketRegistry)
- **Authentication**: session token only, no API keys, ever
- **Storage today**: SQLite + JSONL + Markdown
- **Storage future (ADR-011)**: Parquet catalog via NautilusTrader sibling app
- **LLM**: Anthropic via session token for the agent, no LLM for trading core,
  optional local Gemma later via fine-tune on the lesson corpus
- **Strategy style**: Druckenmiller conviction sizing for long horizon +
  bot-pattern exploitation for tactical
- **Risk philosophy**: hard floors + dynamic sizing, not per-trade caps
- **Authority**: per-asset delegation (`agent` / `manual` / `off`), system-wide
  tier ladder (WATCH / REBALANCE / OPPORTUNISTIC), kill switches per subsystem
- **Self-improvement**: L0–L5 contract — learn within bounds, never restructure
  without one tap
- **Documentation**: living wiki + archived plan snapshots + append-only build-log
- **Multi-interface**: Telegram now, web display + voice + screenshot Horizon 1,
  workspace web Horizon 2. **Never rebuild hyperliquid.xyz.**
- **Historical data**: append-only forever, market-correlated going forward,
  searchable

---

## What to do next (concrete, ranked)

The next ten things to ship, in priority order:

1. **Land the parallel-agent burst from this realignment session** —
   user-action queue iterator, entry critic verification, chat history
   correlation + rotation stop, /feedback hardening with FTS5-ready event
   semantics.
2. **Real $50 BTC vault smoke test** — your finger on the button;
   validates lesson_author + entry_critic in production simultaneously.
3. **Sub-system 6 final wedges** — reflect proposals (L2) auto-promotion
   gates, pattern library growth (L3 — manual today, automated in next wedge).
4. **Multi-Market Wedge 2** — thesis JSON schema generalisation (any HL market).
5. **Brutal Review Loop Wedge 2-3** — scheduled cadence (weekly) +
   action queue parser (so the brutal report's recommendations land in
   the user-action queue automatically).
6. **Knowledge Graph Thinking Regime — Wedge 1** — write the plan doc
   (`docs/plans/KNOWLEDGE_GRAPH_THINKING.md`) and prototype a concept
   graph for one decision context (e.g. "considering an oil short").
7. **Telegram monolith Wedge 2** — extract `cli/telegram_commands/portfolio.py`
   (cmd_status, cmd_position, cmd_pnl).
8. **ADR-011 Tier 1 wins** — snapshot bleeding fix, daily report data-driven,
   Phase 3 REFLECT loop wiring. These unlock the `quant/` sibling app build.
9. **Voice / screenshot capture in Telegram** — the lower-friction thesis
   input promised in Horizon 1.
10. **Refresh or formally park** the GOLD + SILVER theses.

After these ten land, the next NORTH_STAR rewrite will be at the natural
boundary of "Horizon 1 substantially shipped." Until then, this version
holds.

---

## Versioning of this document

Same convention as MASTER_PLAN.md. When the vision shifts meaningfully,
archive to `docs/plans/archive/NORTH_STAR_YYYY-MM-DD_<slug>.md` (append-only,
HTML-comment header explaining WHY it was archived and what it got wrong)
and rewrite this file fresh. The vision should not need to move often —
when it does, the move is worth recording.

> Past versions: see `docs/plans/archive/` (oldest first by filename sort).
> The 2026-04-09 morning version was archived because it missed the
> founding philosophy, the authority model, and the L0–L5 contract. Read
> it for the lesson on what happens when you write vision docs without
> reading git history first.
