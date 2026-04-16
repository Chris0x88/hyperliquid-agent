# Brutal Review Loop

> **Goal**: a periodic deep-honesty audit system that grades the codebase,
> the trading performance, and the decision quality. Distinct from
> Guardian's continuous shallow drift detection. Produces a brutal,
> specific, actionable report — not a summary.
>
> **Triggered by**: Chris's request 2026-04-09 after the manual deep-dive
> review revealed MASTER_PLAN staleness, lesson corpus pollution, and
> a journal schema mismatch — none of which Guardian had caught because
> they're all "is this still true?" questions, not "is this connected?" questions.
>
> **Status**: Proposed. Wedge 1 ready to start in parallel with Multi-Market
> Wedge 1.

---

## Why Guardian + Alignment are not enough

| Layer | What it catches | What it misses |
|---|---|---|
| **Guardian (continuous, every session)** | Orphans, parallel tracks, telegram-completeness gaps, plan/code reference mismatches, NEW: stale plan claims | Quality of trading decisions, codebase smells, doc-vs-reality drift on freeform claims, compounding technical debt, "is this idea still good?" questions |
| **Alignment (session-bookend ritual)** | Drift in docs vs running processes, daemon state, thesis freshness | Same blind spots as Guardian — both are *structural* checks |
| **Build log** | Records what shipped | Cannot grade what shipped |
| **Tests** | Asserts code does what it's supposed to | Cannot tell you if "what it's supposed to do" is the right thing to do |

The thing the manual 2026-04-09 deep-dive caught that none of the above
would have caught:

1. MASTER_PLAN.md said "lesson layer wiring deferred" when it had shipped.
   *(Fixed in this session by Guardian's new `detect_stale_plan_claims()` —
   but only because a human flagged it first.)*
2. The lesson corpus contained 46 fake test fixtures actively poisoning
   BM25 retrieval. *(No structural check could have caught this — it's a
   data-quality problem.)*
3. `data/research/journal.jsonl` had 10 rows with the wrong schema that
   the lesson_author iterator was silently skipping. *(No structural check
   would have caught this either — the file existed, the iterator existed,
   the wiring existed; only running the data through the pipeline reveals
   it.)*
4. `telegram_bot.py` is 4,200+ lines of monolith and growing. *(Guardian
   sees the file but has no notion of "this should be smaller.")*
5. `data/memory/memory.db` had no backup strategy at all. *(Guardian sees
   the file but has no notion of "this is a SPOF.")*

These are **judgment-quality** problems, not **structural** problems.
They need an LLM with the codebase loaded, the right prompt, and
permission to be brutal.

---

## What the loop does

Once a week (configurable), an automated agent invocation runs a
**deep-dive review pass** against the codebase, the trading state, and
the documentation. It produces a single markdown report with sections
that mirror the manual review Chris received on 2026-04-09:

1. **Reality snapshot** — current LOC, test count, iterator count,
   command count, agent tool count, ADR count. Pulled live from code,
   not docs.
2. **What shipped this week** — read from git log + build-log; flag
   anything that shipped without a build-log entry.
3. **Drift findings** — Guardian's drift_report.json AS-IS, but with
   the new `stale_plan_claims` section forced to be acted on, not just
   acknowledged.
4. **Plan freshness audit** — for each file in `docs/plans/`, when was
   it last modified, what does it currently claim, are those claims
   still true. The Plan archive convention from MAINTAINING.md is
   enforced here — anything stale must be archived + rewritten or the
   finding stays open.
5. **Codebase smells** — known anti-patterns:
   - Files >2000 LOC (`telegram_bot.py` is the obvious one)
   - Modules with low test coverage relative to their criticality
   - Functions >100 LOC
   - TODOs/FIXMEs with no associated build-log entry
   - Duplicate config files
   - Dead config files (referenced nowhere)
   - Iterator files not registered in any tier
   - Telegram handlers not in HANDLERS dict
6. **Trading performance grade** — equity curve last week, drawdown,
   win rate, average ROE on closed trades. Compared against the
   Druckenmiller-style targets from NORTH_STAR.md. Honest grade
   (A through F).
7. **Decision quality grade** — for each closed trade, compare:
   - The thesis at open vs the actual market move
   - The lesson the dream cycle authored
   - Chris's review flag
   - Did the conviction band match the actual edge that materialized?
8. **Lessons corpus health** — count, % approved, % rejected, %
   pending, BM25 search test (does a known query return relevant
   lessons), oldest unreviewed lesson age.
9. **Memory.db backup health** — most recent snapshot age, integrity
   check status, restore drill recency.
10. **Open Questions audit** — every "Open Question" in MASTER_PLAN.md
    NORTH_STAR.md / active plan docs. For each, has it moved? If yes,
    update the doc. If no for >30 days, escalate.
11. **Architecture coherence** — does the wiki current.md still match
    reality? Sample 5 random claims and verify against running code.
12. **Top 5 brutal observations** — the LLM is given explicit
    permission to be honest, not diplomatic. "This is the worst part
    of the codebase right now and here's why" — top 5.
13. **Recommended action list** — concrete, ranked, sized. Each item
    is actionable in one session.

The report is **NOT a summary**. It is the level of detail Chris
received in the manual deep-dive: file paths, line numbers, specific
counts, named claims, named gaps.

---

## How it's invoked

### Cadence

- **Weekly** by default — Sunday evening Brisbane time, before the
  trading week opens.
- **On-demand** via `/brutalreview` Telegram command (AI-suffix
  required since it's LLM-driven: `/brutalreviewai`).
- **Triggered** by the existing scheduled-tasks system (per
  `mcp__scheduled-tasks__create_scheduled_task` in agent-cli's
  scheduler integration).

### Mechanics

1. A new daemon iterator OR a scheduled task wakes the agent with a
   highly specific prompt — see `Prompt template` below.
2. The agent runs through the prompt's checklist using its existing
   tools: `search_code`, `read_file`, `list_files`, `run_bash` (for
   git log + sqlite queries + pytest counts), `search_lessons`,
   `account_summary`, `trade_journal`.
3. Output is written to `data/reviews/brutal_review_YYYY-MM-DD.md`.
4. A short summary + the action list is posted to Telegram.
5. Each action item becomes a tracked TODO that the next session sees
   on its alignment run.

### Tools the agent needs (mostly already exist)

- `read_file`, `list_files`, `search_code` ✅
- `run_bash` (for git log, pytest, sqlite queries) ✅
- `search_lessons`, `get_lesson` ✅
- `account_summary`, `trade_journal` ✅
- **NEW**: `read_drift_report` — read the latest Guardian drift_report.json
- **NEW**: `read_build_log_since(date)` — slice build-log from a date
- **NEW**: `count_files_matching(pattern)` — for "files >2000 LOC" smell

The two NEW tools are thin wrappers on existing capabilities.

---

## Prompt template (the spirit, not the literal)

The agent is invoked with a system prompt that says:

> You are running the weekly Brutal Review Loop. Your job is to produce a
> brutally honest, specific, file-and-line-cited audit of this codebase
> and the trading state. You are NOT writing a summary. You are NOT being
> diplomatic. Chris explicitly asked for honest feedback over comfortable
> consensus — that is principle P8 in NORTH_STAR.md.
>
> Read these files first to ground yourself in current reality (do NOT
> trust your memory — read them):
> - docs/plans/MASTER_PLAN.md
> - docs/plans/NORTH_STAR.md
> - docs/wiki/build-log.md (most recent 5 entries)
> - guardian/state/drift_report.md
> - data/research/journal.jsonl (most recent 30 entries)
>
> Then run the 13-section audit defined in BRUTAL_REVIEW_LOOP.md. For
> each section, produce findings with file paths and line numbers. For
> the "Top 5 brutal observations" and "Recommended action list" sections
> you have explicit permission to call out things Chris would rather not
> hear. The 2026-04-09 manual review is the gold standard — match its
> tone and depth.
>
> Hard rules:
> - Do not invent metrics; if you don't know, run the command
> - Do not soften findings; "this is fine" is only acceptable when it actually is
> - Do not skip sections; if a section is N/A, say so explicitly
> - End with the action list, ranked by ROI

The prompt itself becomes a test of the loop — Chris reads the first
report and tunes the prompt until it produces output as good as the
manual review.

---

## The wedges

### Wedge 1 — Manual invocation + report writer

**What ships:**
- New file `agent-cli/docs/plans/BRUTAL_REVIEW_PROMPT.md` containing
  the literal system prompt (separate from this design doc so it can
  be iterated without rewriting the design).
- New Telegram command `/brutalreviewai` in `cli/telegram_bot.py` that
  invokes the agent with the BRUTAL_REVIEW_PROMPT.md prompt and writes
  the output to `data/reviews/brutal_review_YYYY-MM-DD.md`.
- Test in `tests/test_telegram_brutalreview_command.py` covering the
  handler dispatch and output file format.
- Full 5-surface registration per the Telegram command checklist.
- New directory `data/reviews/` with a `.gitkeep`.

**Definition of done**: Chris runs `/brutalreviewai`, the agent produces
a report that is at least 80% as good as the 2026-04-09 manual review,
the report is on disk and summarised to Telegram.

### Wedge 2 — The two new tools

**What ships:**
- `read_drift_report` and `read_build_log_since(date)` in
  `cli/agent_tools.py`.
- `count_files_matching(pattern, max_loc, min_loc)` for codebase smell
  audits.
- Tests in `tests/test_agent_tools.py`.

### Wedge 3 — Scheduled cadence

**What ships:**
- A scheduled-tasks entry that fires `/brutalreviewai` weekly on Sunday
  evening Brisbane time.
- Brisbane timezone handled via the existing scheduler conventions.
- Notification on completion to the same chat_id as other Telegram alerts.

### Wedge 4 — Action list → TODO sync

**What ships:**
- Parser for the report's "Recommended action list" section.
- Each action becomes a row in a new `data/reviews/action_queue.jsonl`
  with status `pending` / `in_progress` / `done` / `dismissed`.
- New Telegram command `/reviewactions` (deterministic) shows pending items.
- Alignment workflow reads the action queue and surfaces it on session start.

### Wedge 5 — Decision-quality grading

**What ships:**
- A scoring function: for each closed trade, compute (thesis_conviction,
  realised_ROE_normalized, holding_hours, exit_cause) and grade as
  GOOD / OK / BAD / UNCLEAR.
- Aggregated weekly into the report's section 7.
- Backed by tests using fixture trades with known good/bad outcomes.

### Wedge 6 — The "Top 5 Brutal" section is not optional

**What ships:**
- Validation in the report writer that section 12 has exactly 5 items
  and each is at least 100 chars (i.e., specific, not "looks good").
- If the agent produces fewer than 5 specific brutal findings, the
  report is rejected and the agent is re-prompted with a stricter
  framing.
- This is the difference between a useful review and a comfort blanket.

---

## What this plan deliberately does NOT do

- **Does not** replace Guardian. Guardian is continuous + structural.
  Brutal Review is periodic + judgment-driven. They run side by side.
- **Does not** auto-fix things. The whole point is to surface things
  for Chris to decide. Auto-fix is what Guardian's review gate is for.
- **Does not** gate trading. The brutal review can grade performance F
  and the daemon keeps running. Killing trading is what the kill
  switches and drawdown brakes are for.
- **Does not** publish anywhere outside Chris's Telegram + local disk.
  Brutal honesty about a personal trading system is for the system's
  owner only.

---

## How this fits into the larger arc

| System | Cadence | Depth | Action |
|---|---|---|---|
| **Tests** | On every change | Deep on code correctness | Block merge |
| **Guardian drift** | Every Claude session | Shallow + structural | Flag, sometimes block |
| **Alignment** | Session bookends | Doc-vs-reality | Manual fix |
| **Build log** | Per shipped feature | Append-only history | Record |
| **Brutal Review Loop** | Weekly + on demand | Deep + judgment | Action list |
| **Manual deep-dive** | Rare, on big inflection | Deepest | Strategic pivot |

The loop slots between alignment (too shallow) and manual deep-dive (too
rare). It's the *sustainable* version of the 2026-04-09 review.

---

## Risks & mitigations

| Risk | Mitigation |
|---|---|
| The agent produces a fluffy "everything is fine" report | Wedge 6 — explicit validation that section 12 has 5 specific items, re-prompt if not |
| Chris stops reading the reports because they're long | Telegram summary is short; full report only opened on demand; action queue is the actually-actionable surface |
| The prompt becomes stale and the reports get worse | The prompt itself lives in `BRUTAL_REVIEW_PROMPT.md` and is versioned/archived per the same convention as other plans |
| Cost of running this weekly | Session-token auth means $0 marginal cost. Cadence is once a week — even at heavy token use this is cheap. |
| The action list grows faster than Chris can clear it | Wedge 4 includes a `dismissed` status; some items are documented "won't fix" and that's fine. The honesty matters more than the throughput. |

---

## Definition of Done

- `/brutalreviewai` produces a report on demand that matches the depth
  and specificity of the 2026-04-09 manual review.
- A weekly scheduled task runs the loop without human intervention.
- The action queue is being worked through (some items every week
  marked done, some dismissed, some carried forward).
- The first report flags at least 3 things Chris didn't already know
  about the codebase.
- After 3 months of running, the action list has materially shaped at
  least one strategic decision.

---

## Versioning

Same convention as the other plans. Archive + rewrite when the loop
itself changes character.

> Past versions: see `docs/plans/archive/`.
