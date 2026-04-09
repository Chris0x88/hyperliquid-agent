---
kind: architecture
title: Time-Loop Interweaving — How Processes Weave Through Time
last_manual_update: 2026-04-09
source_phases:
  - SYSTEM_REVIEW_HARDENING_PLAN Phase C §5
tags:
  - architecture
  - time-loops
  - cadence
  - interweaving
  - drift-detection
---

# Time-Loop Interweaving — How Processes Weave Through Time

> **Hand-written page.** The vault auto-generator does NOT touch
> this file. It captures the time dimension of cohesion: which
> iterators write what, at what cadence, with what worst-case
> latency to the consumer iterator — the chain-of-custody for
> a signal as it travels through the system.
>
> This is the page the user explicitly asked for in the 2026-04-09
> review dispatch: *"the element of time loops in that process too
> so we track processes that interweave and not just waterfall code
> structure alone."*

**Source audit:** `docs/plans/TIMER_LOOP_AUDIT.md` §5 (Phase C of
`SYSTEM_REVIEW_HARDENING_PLAN.md`).

## The execution model in one picture

The system is **not a waterfall**. It is three concurrent loops
(daemon / telegram / heartbeat) plus out-of-process AI commands,
all writing into a single shared filesystem. Each iterator within
the daemon loop has its own cadence on top of the global 120 s
tick. Cadences drift randomly against each other.

```
  t=0 ─────────────────── t=60 ────────────── t=120 ─────── t=180 ────► time
       daemon tick 1                            daemon tick 2
         ├─ account_collector  (every tick)
         ├─ connector          (every tick)
         ├─ news_ingest        (60 s self-throttle) ← runs ~every other tick
         ├─ supply_ledger      (300 s self-throttle) ← runs ~every 3 ticks
         ├─ heatmap            (every tick, but heavy)
         ├─ bot_classifier     (300 s self-throttle) ← runs ~every 3 ticks
         ├─ oil_botpattern     (60 s self-throttle, shadow mode today)
         ├─ ...
         └─ telegram drain     (queue alerts)

  telegram process (separate):
         user sends message
            ↓
         agent_runtime (in-process)
            ↓
         AI tool calls  →  write to shared data/
            ↓
         can collide with daemon iterator writing same file

  heartbeat process (separate, launchd respawn every 120 s):
         read positions → set missing exchange SLs
```

## Cross-iterator signal chains (the interweaving)

Each chain describes one signal's journey from source to trading
decision, with the **worst-case end-to-end latency** at today's
configured cadences.

### Chain C1 — Catalyst → Strategy (the Oil Bot-Pattern pipeline)

```
news_ingest (60 s)
   ├─ writes: data/news/catalysts.jsonl (append)
   ↓  (can sit for up to 300 − 60 = 240 s before supply_ledger reads)
supply_ledger (300 s)
   ├─ reads: data/news/catalysts.jsonl
   ├─ writes: data/supply/state.json
   ↓  (can sit for up to 300 − 300 = 300 s before bot_classifier reads;
   │   phase drift makes the worst case 600 s for identical cadences)
bot_classifier (300 s)
   ├─ reads: data/supply/state.json, data/news/catalysts.jsonl, candle cache
   ├─ writes: data/research/bot_patterns.jsonl (append)
   ↓  (can sit for up to 300 − 60 = 240 s before oil_botpattern reads)
oil_botpattern (60 s)
   └─ reads: data/research/bot_patterns.jsonl
```

**Worst-case total latency:** ≈240 + 300 + 240 = **12 minutes**.

A severity-5 Hormuz-blockade catalyst can sit in `catalysts.jsonl`
for 12 minutes before the strategy sees it. That defeats the point
of a shock-reactive oil strategy. See `COHESION_HARDENING_LIST.md`
P0-2 for the fast-path fix.

### Chain C2 — AI thesis update → Daemon decision

```
AI agent update_thesis tool (telegram process, on-demand)
   ├─ writes: data/thesis/xyz_brentoil_state.json (atomic rename assumed)
   ↓  (at most one daemon tick = 120 s before thesis_engine re-reads)
thesis_engine (60 s self-throttle inside daemon tick)
   ├─ reads: data/thesis/xyz_brentoil_state.json
   ├─ writes: computed conviction into ctx
   ↓
execution_engine or oil_botpattern
   └─ reads ctx.conviction → trading decisions
```

**Happy-path latency:** ≤60 s (next thesis_engine tick).

**Race window:** if the AI writes mid-read, the daemon sees a
half-written JSON file, fails to parse, and falls through silently
to the previous conviction. Stale conviction drives a live trading
decision. See `COHESION_HARDENING_LIST.md` P0-5.

### Chain C3 — Closed trade → Lesson → Next agent decision

```
execution_engine closes a position
   ├─ writes: data/research/journal.jsonl (append)
   ↓  (at most 120 s = one tick)
lesson_author (every tick)
   ├─ reads: data/research/journal.jsonl
   ├─ writes: lesson candidate file → common/memory.py log_lesson
   ↓
AI agent on next decision
   └─ reads: top-5 lessons via search_lessons tool
```

**Happy-path latency:** one tick (120 s) to have the lesson row
written, plus however long until the next AI decision.

**Restart failure mode:** `journal._prev_positions` is in-memory
only. If the daemon restarts between the close event and the
`journal` iterator's next tick, the close is silently dropped — no
lesson written, no row in the journal, no signal to the learning
layer. See `COHESION_HARDENING_LIST.md` P0-3.

### Chain C4 — L1 tune → Sub-system 5 config → Next tick

```
oil_botpattern_tune (300 s self-throttle)
   ├─ reads: closed-trade journal
   ├─ writes: data/config/oil_botpattern.json (rewrite, atomic-rename)
   ↓  (next tick)
oil_botpattern (60 s self-throttle)
   └─ reads: data/config/oil_botpattern.json
```

**Happy-path latency:** one daemon tick after the tune write.

**Race window:** Telegram `/selftuneapprove` can rewrite the same
file from the telegram process at the same instant. Last-writer-wins
silently erases one side's edit. Today both sides are kill-switched
so the race is dormant; **when either side flips on, the race is
hot.** See `COHESION_HARDENING_LIST.md` P1-3.

### Chain C5 — User nudge → Action queue → Telegram alert

```
action_queue iterator (24 h wall-clock cadence)
   ├─ reads: data/user_actions.jsonl or equivalent
   ├─ scans: cadence + last-done timestamps
   └─ appends: alert to ctx.alerts
telegram iterator (every tick, drains ctx.alerts)
   └─ sends Telegram message
```

**Happy-path:** 24 h cadence fires → alert queued same tick →
telegram drains alert same tick → user receives message within
120 s of the cadence firing.

**Restart failure mode:** if the daemon restarts every ~6 h
(e.g. crash loop), the 24 h cadence never elapses because
`_last_run` is in-memory and resets. The nudge never fires. See
`COHESION_HARDENING_LIST.md` P1-6 and meta-finding M3.

### Chain C6 — Heatmap zones → (consumer)

```
heatmap (every tick)
   ├─ writes: data/heatmap/zones.jsonl (append) ← UNBOUNDED GROWTH
   └─ writes: data/heatmap/cascades.jsonl (conditional) ← FILE MISSING TODAY
```

**Worst case:** `zones.jsonl` grows without retention. Every tick
appends ~200 rows. Over 24 h that's ~600 MB of zones.

**Mystery:** `cascades.jsonl` does not exist on disk. Either no
cascade has been detected (plausible — BRENTOIL is quiet), or the
write path is silent-failing. See `COHESION_HARDENING_LIST.md`
P0-6 for the trace-the-write-path task.

### Chain C7 — Sub-system 6 L2 reflect → L4 shadow → Proposal approval

```
oil_botpattern_reflect (7 d wall-clock — if it ever elapses)
   ├─ reads: closed-trade journals
   ├─ writes: data/strategy/oil_botpattern_proposals.jsonl
   ↓  (next tick)
oil_botpattern_shadow (3600 s throttle)
   ├─ reads: proposals jsonl
   ├─ writes: ShadowEval records into the same file (atomic-rewrite)
   ↓  (human review)
Telegram /selftuneapprove (telegram process)
   └─ rewrites the proposal row to status=approved
```

**Race window:** shadow iterator and telegram both rewrite
`oil_botpattern_proposals.jsonl`. Today this is dormant (L2 kill
switch off), but when L2 activates, the proposals-jsonl rewrite
race becomes active. See `COHESION_HARDENING_LIST.md` P2-1.

**Long-cadence risk:** the 7-day window never elapses unless the
daemon has 7 days of continuous uptime. Observed uptime median is
much shorter. See `COHESION_HARDENING_LIST.md` M3.

## Phase-drift cases

When two iterators have cadences that are close but not equal, they
drift in phase over time:

- `memory_consolidation` (3600 s) + `memory_backup` (3600 s wall-clock)
  — both fire hourly. Phase offset depends on startup order. If
  backup fires mid-consolidation, the backup may contain a partial
  write. The `memory_consolidation → memory_backup` ordering invariant
  is currently un-documented but happens to hold because of the
  `tiers.py` list order. See `COHESION_HARDENING_LIST.md` P2-4.
- `news_ingest` (60 s) + `heatmap` (every tick = 120 s) — close
  enough that they will re-phase every 2 minutes; no interaction
  because they write disjoint files.

## Long-window cadences

Any iterator whose cadence is longer than expected daemon uptime
between restarts MUST be wall-clock-scheduled or it will never
actually fire:

| Iterator | Cadence | Scheduling | Fires reliably? |
|---|---|---|---|
| `memory_backup` | 1 h | wall-clock | ✅ |
| `memory_consolidation` | 1 h | monotonic `_last_tick` | ⚠️ resets on restart |
| `action_queue` | 24 h | monotonic `_last_run` | ⚠️ resets on restart |
| `oil_botpattern_reflect` | 7 d | monotonic | ❌ rarely elapses |
| `oil_botpattern_tune` | 5 min | monotonic | ✅ (short enough that resets don't matter) |
| `brent_rollover_monitor` | checks rollover calendar | wall-clock | ✅ |
| `news_ingest` | 60 s | monotonic | ✅ |

See `COHESION_HARDENING_LIST.md` P1-6 + M3 for the fix pattern:
replace monotonic `_last_run` with a persisted `last_run_wallclock_ts`
in every >1 h iterator's state file.

## The rule

**Any time you add a new iterator, write its chain in this page.**
A one-paragraph entry in the "Cross-iterator signal chains" section
is enough. If you can't articulate the chain from source to trading
decision, you haven't thought about the iterator's place in the
system yet.

**Any time you change a cadence**, re-verify the worst-case latency
of every downstream chain. The drift multiplies.

**Any time an iterator's cadence is >1 h**, use wall-clock
scheduling, not monotonic.

## Related

- `docs/vault/architecture/Cohesion-Map.md` — the *who writes what*
  companion to this *when do they write it* page.
- `docs/vault/runbooks/Drift-Detection.md` — how to spot changes to
  the iterators listed above.
- `docs/plans/TIMER_LOOP_AUDIT.md` — the Phase C audit that this
  page is the hand-written summary of.
- `docs/plans/COHESION_HARDENING_LIST.md` — the P0/P1/P2 backlog
  derived from this analysis.
- `docs/plans/VAULT_AS_AUDITOR.md` — the proposal to automate the
  time-loop drift detection that this page does by hand.
