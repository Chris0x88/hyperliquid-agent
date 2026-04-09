<!--
ARCHIVED: 2026-04-09 evening
Reason: Snapshot of NORTH_STAR.md taken immediately before the
2026-04-09 philosophy-realignment session. This version was written
earlier in the same day but contained THREE foundational errors that
the user (Chris) flagged in the brutal-feedback message that triggered
the realignment:

  1. Operating Principle P6 ("One human in the loop, always") was wrong.
     The system has a mature per-asset delegation model in
     common/authority.py with three levels (agent / manual / off) and
     the WATCH/REBALANCE/OPPORTUNISTIC tier ladder. Authority is
     parameterized, not absolute.

  2. The dumb-bot trading philosophy — the FOUNDING insight of the
     entire active workstream, captured in OIL_BOT_PATTERN_SYSTEM.md
     §1 ("Markets are dumb. ~80% of trades are bots reacting to known
     information... A petroleum engineer trying to forecast the
     fundamental gets killed by bots that don't read the supply
     ledger.") — was not referenced anywhere in this version. NORTH_STAR
     should LEAD with it, not bury it.

  3. NautilusTrader inspiration → ADR-011's two-app research-sibling
     plan was namedropped as "the parked research-app" without
     understanding it IS the quant-data architecture answer to Chris's
     stated quant ambitions.

This snapshot is preserved unmodified so the realignment is traceable
and the rewrite can be diffed against the version that motivated it.

DO NOT EDIT.
-->

# NORTH STAR

> The single document that says **what we are building, why, and what good looks like**.
> Read this once, then anchor every decision against it.
> When this document changes, archive the prior version like MASTER_PLAN.md.

---

## Why this exists

Chris is a petroleum engineer with deep, real-world commodity expertise.
He has **strong ideas** and the ability to **make a lot of money**, and a
clear-eyed view of his own weakness:

> *"I am terrible at executing and staying disciplined."*

That sentence is the entire reason this system exists. Most retail traders
fail at execution and discipline; what makes this project tractable is that
the *ideas* are not the problem. The system's job is to be **the discipline
Chris cannot reliably supply by hand**, while letting his actual edge — the
ideas — flow through unimpeded.

This is not a trading bot. It's a **prosthetic for execution discipline**
that happens to trade on HyperLiquid.

---

## The Three Promises

The system makes three promises to Chris and is judged against them:

### 1. Capture every good idea before it evaporates
Ideas surface during reading, calls, market events, the shower. The system
must make it trivial to write a thesis, log a catalyst, or note a pattern
*in the moment*, with zero friction. Telegram is the catch surface today;
multi-modal capture (voice, OCR, screenshot) is on the roadmap.

**Test of success**: when Chris has a thought at 11pm, can he turn it
into a structured input the system understands within 60 seconds, without
opening a laptop?

### 2. Execute the idea with discipline a human can't sustain
Once an idea is captured, the system enforces:
- Mandatory exchange-side stop loss + take profit on every position
- Conviction-based sizing (more conviction → more risk, less conviction → less risk)
- Drawdown circuit breakers (3% daily / 8% weekly / 15% monthly) as ruin floors
- Catalyst-driven deleveraging when invalidating events occur
- Auto-clamping when thesis becomes stale

**Test of success**: when Chris is asleep / busy / emotional, the system
behaves identically to when he is watching. The only difference is reaction
time on novel events, which the alert system handles.

### 3. Learn from every trade, automatically
Every closed position becomes a structured post-mortem. The corpus is
searchable. The next decision is informed by the most relevant past lessons.
Bad reasoning gets caught by future-Chris reading past-Chris's lessons.

**Test of success**: in 12 months, the agent should be quoting specific
lesson IDs in its reasoning ("Lesson #142 says supply-driven longs work
when entry is >24h ahead of the catalyst — this setup is late, sizing
down").

---

## What This Project Is NOT

A clear no-list prevents scope creep:

- **Not a strategy marketplace.** No selling signals, no Discord, no public alpha.
- **Not a paper-trading sandbox.** Real capital from day one. Mock mode exists for testing only.
- **Not a generic algo platform.** It is shaped around Chris's specific edge and weaknesses.
- **Not a fully autonomous bot.** Chris is in the loop on every WRITE tool call. The system is *autonomous in execution discipline*, *human-in-the-loop on strategic direction*.
- **Not free to evolve unchecked.** Mandatory tests, mandatory backups, mandatory ADRs for architectural decisions. Discipline applies to the codebase too.
- **Not coupled to any cloud provider.** Local-first by design. Session-token auth means zero ongoing API cost. Data lives on disk.

---

## The Three Horizons

### Horizon 1 — 0 to 12 months: **Multi-market discipline platform**

Today the system trades BTC + oil with mature scaffolding. By the 12-month
mark it should:

- Trade any HL market (perp or spot) Chris promotes to thesis-driven, via
  config + thesis JSON, with zero code changes per market. (See `MULTI_MARKET_EXPANSION_PLAN.md`.)
- Carry market-shape metadata (long-only / long-short / no-direction-bias)
  per instrument so the oil-only rule generalises.
- Have a populated lessons corpus of 100+ real post-mortems with Chris-reviewed approval flags.
- Run a brutal weekly review loop that grades the codebase, the trading
  performance, and the decision quality, surfaced as a Telegram report.
  (See `BRUTAL_REVIEW_LOOP.md`.)
- Have first-class voice and screenshot capture for thesis input.
- Be running 24/7 on dedicated hardware (not Chris's laptop).

### Horizon 2 — 12 to 24 months: **Edge compounding**

By month 24:

- The lessons corpus has trained at least one local LoRA adapter on
  Gemma-3 (or successor) that meaningfully improves recall of Chris's
  reasoning style on held-out replay tests.
- A structured backtest harness can replay any thesis against historical
  data to estimate forward edge before promoting.
- A "shadow trade" mode runs proposed strategies on live data without
  real capital, building a track record before promotion.
- The bot_classifier (currently heuristic) is augmented with a real
  classifier trained on labelled data from the supply ledger + cascade
  history.
- Drawdown circuit breakers have prevented at least one ruin event
  (and the post-mortem is a lesson Chris quotes regularly).
- Realised compounding rate has cleared a clearly-defined target the
  system itself tracks against.

### Horizon 3 — 24 to 36+ months: **Quietly excellent**

By month 36 the system should be the kind of personal infrastructure most
traders never build: invisible when working, indispensable when needed.

- Multi-instrument, multi-strategy, multi-timeframe, single human in the loop.
- Auto-tunes its own gate thresholds within Chris-approved bounds.
- Self-audits weekly via the brutal review loop and produces an action list.
- Surfaces market opportunities Chris hasn't thought of yet, ranked by
  thesis-fit and sized by conviction proxies.
- Runs on dedicated hardware that Chris does not have to babysit.
- Has a clean separation between "personal infrastructure" and "potentially
  shareable framework" — if Chris ever decides to extract a public
  framework or hand pieces to other traders, the boundary is clear.

---

## Operating Principles (the rules behind the rules)

These are the principles every architectural decision should be checked against.

### P1 — Discipline is the product, not a constraint
Every protection (mandatory SL+TP, drawdown brakes, conviction clamps,
kill switches) exists because Chris explicitly asked for it after losing
something to its absence. Removing a protection requires a stronger
argument than "it's annoying." The annoyance IS the value.

### P2 — Reality first, docs second
Code that runs is the truth. Docs that describe what the code USED to do
are worse than no docs at all. The Brutal Review Loop and Guardian
drift detection enforce this.

### P3 — Local-first, no rent
Session-token auth, SQLite storage, launchd-managed daemons, no cloud
services. The system runs forever for free. The day it stops being
local-first is the day it starts costing money you don't see.

### P4 — Additive over destructive
When in doubt, disable rather than delete. Quarantine rather than
overwrite. Archive rather than rewrite-in-place. CLAUDE.md "no destructive
overreach" rule exists for a reason.

### P5 — Confirm before building, commit per logical unit
The 2026-04-07 hardening session wasted time writing a 600-line ADR based
on a stale picture. The 2026-04-09 sub-system 5 plan was rejected and
rewritten in 2 minutes — saving 2 hours of code. Plans are cheap; rewrites
of working code are expensive.

### P6 — One human in the loop, always
WRITE tools require approval. Position-touching commands require
confirmation. Even when fully trusted, the bot does not act on its own
authority on trade actions. The day Chris removes the approval gate is
the day a typo costs an account.

### P7 — Compounding wealth is the only goal
Per Chris's verbatim framing in build-log 2026-04-09 sub-system 5:
> Compound wealth as fast as possible (without tanking the account).
> Put me under pressure to perform and take risk to make big money when
> I have a high edge, and bet less money when my edge is small.

Every sizing decision, every gate, every conviction band cascades from
this. Caps are bad; conviction-driven dynamic sizing is good. Drawdown
brakes are the floor that makes aggressive sizing safe.

### P8 — Honest feedback over comfortable consensus
The system must be **brutally honest** in its self-reporting. A weekly
review that grades the codebase a C+ is more valuable than one that grades
it an A- to make Chris feel good. The Brutal Review Loop is the formal
mechanism for this; the spirit applies to every PR comment, every wiki
update, every alignment run.

---

## What "Startup-Quality" Means For This Project

Chris asked for the system to be "fucking amazing… startup-quality." That
phrase needs unpacking because *startup* implies things this project
explicitly is NOT (multi-tenant, customer-facing, growth-optimized).

The right reading: **the engineering hygiene of a well-run early-stage
fund's internal trading desk.** Specifically:

| Dimension | What good looks like |
|---|---|
| **Test coverage** | >90% on trade-touching code; deterministic tests for every gate; ✅ already at ~52% test:code ratio (2,500+ tests) |
| **Backups** | Hourly automated, integrity-checked, restore-drilled. ✅ shipped 2026-04-09 |
| **Audit trail** | Every order, every decision, every reasoning step in append-only logs ✅ |
| **Kill switches** | Every subsystem has one. Default-off for new risky things ✅ |
| **Drawdown protection** | Hard floors that auto-trigger before Chris knows there's a problem ✅ |
| **Documentation** | Wiki + ADRs + build-log + plans + memory ✅ |
| **Drift detection** | Continuous (Guardian) + periodic deep audit (Brutal Review Loop, planned) |
| **Disaster recovery** | Restore drill is documented and runs at least quarterly. **GAP — needs runbook** |
| **Observability** | Metrics for funding cost, equity curve, win rate, lesson approval rate. **GAP — partial** |
| **Reproducibility** | Mock mode for any iterator, replay harness for any past trade. **GAP — partial** |
| **Security** | Session token auth, dual-write secrets, no API keys. ✅ |
| **Code review** | Every meaningful change gets a brutal review pass before merge. **GAP — see Brutal Review Loop** |

The four GAPs above are the next 90 days of work alongside the active
sub-systems.

---

## The "Idea Funnel"

How a Chris idea becomes a money-making position, in 5 stages:

```
   1. CAPTURE                    2. SHARPEN                 3. SIZE
      ───────                       ───────                   ─────
   Telegram /thesis              Agent challenges          Conviction
   Voice memo (planned)          via tools + lessons       0.0 → 1.0
   Screenshot OCR (planned)      Brutal review Q&A         Druckenmiller
                                                            ladder

         ↓                            ↓                        ↓

   4. EXECUTE                    5. LEARN
      ────────                      ─────
   Heartbeat + execution_engine  Journal closes
   Mandatory exchange SL + TP    Lesson candidate
   Drawdown brakes               Dream cycle authors
   Catalyst deleverage           BM25 retrieval at next decision
                                 Approve/reject feedback loop
```

Today: stages 1, 4, 5 are mature. Stages 2, 3 are partial (the agent
*can* challenge, the conviction engine *can* size, but stage 2 needs
more structure — see Brutal Review Loop). The 12-month target is to
make all 5 stages first-class.

---

## Direction-Setting Decisions Already Made

Pinned here so they don't need to be re-litigated:

- **Markets**: BTC + oil to start, expand to all HL via config (no code).
- **Authentication**: session token only, no API keys, ever.
- **Storage**: local SQLite + JSONL, no cloud DBs.
- **LLM**: Anthropic via session token now, optional local Gemma later.
- **Strategy style**: Druckenmiller-inspired conviction sizing, not mean reversion or grid trading.
- **Risk philosophy**: hard floors + dynamic sizing, not per-trade caps.
- **Dev stance**: human in the loop on every WRITE, autonomous on every READ.
- **Documentation**: living wiki + archived plan snapshots + build log.
- **Self-improvement**: lessons corpus + reflect engine + (eventually) local LoRA on real trades.

---

## What to do next (concrete, ranked)

The next ten things to ship, in priority order:

1. **End-to-end smoke test** of the lesson layer with one real $50 trade
   (or a synthetic-but-schema-correct journal entry). Verify journal →
   candidate → dream cycle → memory.db row → BM25 retrieval → prompt injection.
2. **Sub-system 6** of the Oil Bot Pattern System (self-tune harness).
3. **Multi-market expansion Wedge 1** — extract the long-only-oil rule
   into config so other markets can have different direction bias.
4. **Brutal Review Loop wedge 1** — write the cron + agent invocation
   that produces the first weekly report.
5. **Voice / screenshot capture** in Telegram for lower-friction thesis input.
6. **Restore drill runbook** for `data/memory/memory.db` (the iterator
   ships, the drill is undocumented).
7. **`telegram_bot.py` incremental split** into `cli/telegram_commands/`
   submodules (one warmup task per session).
8. **Equity curve + win rate Telegram report** (`/equity`, deterministic).
9. **Replay harness** that takes a frozen account snapshot and lets the
   agent re-decide — the prerequisite for any LoRA training.
10. **Refresh or formally park** the GOLD + SILVER theses.

---

## Versioning of This Document

Same convention as MASTER_PLAN.md. When the vision shifts meaningfully,
archive the old version to `docs/plans/archive/NORTH_STAR_YYYY-MM-DD_<slug>.md`
(append-only) and rewrite this file fresh. The vision should not need to
move often — when it does, the move is worth recording.

> Past versions: see `docs/plans/archive/`.
