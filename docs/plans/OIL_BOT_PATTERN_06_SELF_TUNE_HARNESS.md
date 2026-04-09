# Sub-system 6 — Oil Bot-Pattern Self-Tune Harness

**Slot in `OIL_BOT_PATTERN_SYSTEM.md`:** row 6. Wraps sub-system 5 with a
bounded self-improvement loop. First sub-system in the stack that does NOT
place trades directly — it mutates the parameters #5 reads on its next tick.

**Status:** APPROVED 2026-04-09 (picked up from prior session handoff).
Building now. First ship = **L1 + L2 only**. L3 and L4 get their own plan
docs; L5 remains deferred per SYSTEM doc §6.

## Background

Sub-system 5 shipped 2026-04-09 (`42efb54`) with both kill switches OFF.
It emits decision records to `data/strategy/oil_botpattern_journal.jsonl`
on every tick and appends closed positions to `data/research/journal.jsonl`
with `strategy_id="oil_botpattern"`. The self-tune harness reads those two
streams and nothing else — it does not touch exchanges, orderbooks, or any
external API.

The SYSTEM doc §6 defines six layers (L0-L5). Their status at the start of
this wedge series:

| Layer | Description | Status |
|---|---|---|
| L0 | Hard contracts (tests, SL+TP, schemas) | **Already shipped.** exchange_protection enforces SL+TP; tests live in `tests/`; every config file has a schema via the kill-switch reloader. No work needed here. |
| L1 | Bounded auto-tune — journal-replay nudges params within hard min/max after each closed trade | **This wedge.** |
| L2 | Reflect proposals — weekly structural change proposals to Telegram with 1-tap promote/reject | **This wedge.** |
| L3 | Pattern library growth — classifier auto-adds new bot-pattern signatures | **Deferred to sub-system 6 phase 2.** Needs sub-system 4 classifier extension + versioned catalog + promotion UX. |
| L4 | Shadow trading — proposals run in paper mode for ≥N closed trades before live | **Deferred to sub-system 6 phase 3.** Needs a paper-mode executor — separate surface, separate risk review. |
| L5 | ML overlay | **Deferred per SYSTEM doc §6.** Requires ≥100 closed trades first. Parked indefinitely. |

**Why L1 + L2 first:** they are the two layers that deliver value without
needing fresh plumbing outside sub-system 6 itself. L1 nudges config values,
which is the entire API surface it needs. L2 writes structural proposals to
a JSONL file and emits a Telegram alert — also the whole surface. L3 and L4
each require modifying other sub-systems.

**The contract (copied verbatim from SYSTEM doc §6, non-negotiable):**

> The system is allowed to LEARN automatically. The system is not allowed to
> CHANGE STRUCTURE without one human tap. Crossing that line is how trading
> systems blow up overnight.

L1 LEARNS param values. L2 PROPOSES structural changes but never applies them.

## Parallel-agent hazard

A separate agent is mid-session in this repo building a `memory_backup`
iterator. Their working-tree changes (`cli/daemon/tiers.py`,
`docs/plans/MASTER_PLAN.md`, and the three untracked memory_backup files)
are off-limits. The only file both sides touch is `cli/daemon/tiers.py` —
handled at commit time by stashing their unstaged diff before staging my
registration, committing, and popping the stash back on top. The two sets
of additions are at different positions in each tier list and do not
textually conflict.

---

## L1 — Bounded auto-tune

### What it is

A daemon iterator that watches closed oil_botpattern trades plus the
per-decision journal, then nudges a bounded set of parameters in
`data/config/oil_botpattern.json` after each new closed trade. Every nudge
is audit-logged. Every nudge respects hard YAML-declared min/max bounds.

### Tunable params (bounds ship in `data/config/oil_botpattern_tune.json`)

| Param | Min | Max | Why it's tunable |
|---|---|---|---|
| `long_min_edge` | 0.35 | 0.70 | Entry-floor sensitivity. Too tight → missed setups. Too loose → forced entries on weak signals. Nudges toward whatever the recent winrate suggests. |
| `short_min_edge` | 0.55 | 0.85 | Same as long but higher baseline because shorts are higher-risk. Narrower safe range. |
| `funding_warn_pct` | 0.30 | 1.00 | Early-warning on funding grind. Tight → noisy alerts. Loose → late warning. |
| `funding_exit_pct` | 1.00 | 2.50 | Hard auto-exit on funding cost. Must stay ≥ warn + 0.5. |
| `short_blocking_catalyst_severity` | 3 | 5 | Integer. Minimum catalyst severity that blocks short entries. Nudged based on how often it stopped would-have-been losing shorts. |

### Explicitly NOT tunable (structural)

- `enabled`, `short_legs_enabled` — kill switches, owned by Chris
- `instruments` — market list, owned by Chris
- `drawdown_brakes.*` — ruin floor, structural safety, owned by Chris
- `short_max_hold_hours` — hard safety cap, structural, owned by Chris
- `sizing_ladder[*]` rungs — structural. The L1 loop does NOT touch the
  ladder in this wedge. A proportional scale factor on `base_pct` could
  be a future L1 tunable but shipping without it keeps the blast radius
  minimal. L2 can propose structural ladder changes.
- Any file path field
- `preferred_sl_atr_mult`, `preferred_tp_atr_mult` — exchange_protection
  contract; needs broader review before auto-tune
- `risk_caps.json` contents — owned by global risk policy

### Nudge rule

On each tick with enabled L1, read the last `window_size` closed
oil_botpattern trades (default 20). For each tunable param, compute a
target-direction nudge from outcome statistics, clamp to hard bounds,
cap the step size, and respect the per-param per-24h rate limit:

```
for param in TUNABLE_PARAMS:
    stats = outcome_stats(trades, param)          # winrate, avg_roe, sample_size
    if stats.sample_size < min_sample: continue    # not enough data
    direction = nudge_direction(param, stats)      # +1, -1, or 0
    if direction == 0: continue
    step = min(abs_step, current_value * rel_step) # e.g. max ±5% of current
    proposed = current_value + direction * step
    proposed = clamp(proposed, bounds.min, bounds.max)
    if proposed == current_value: continue
    if last_nudge_age(param) < 24h: continue
    record_nudge(param, current_value, proposed, stats)
    current_value = proposed
```

`nudge_direction` is a per-param heuristic:

- `long_min_edge` / `short_min_edge`: winrate on this direction's trades.
  `winrate > 0.60` → loosen (decrease, more entries). `winrate < 0.40` →
  tighten (increase, fewer entries). Between → no nudge.
- `funding_warn_pct` / `funding_exit_pct`: fraction of longs that closed
  on funding-cost exit. If >30% of long exits were funding-driven AND
  avg_roe on those exits was negative → tighten (decrease, exit sooner).
  If 0% funding-driven exits AND avg long hold > 7 days → loosen.
- `short_blocking_catalyst_severity`: how many blocked shorts WOULD have
  won in hindsight. Requires decision-journal gate reasons. If >60% of
  shorts blocked by this gate would have won → loosen (increase
  severity, fewer blocks). If <20% would have won → tighten.

**Hard-cap the step size** to ±5% of current value (absolute) OR one
minimum-denomination step (integer params → ±1). Maximum one nudge per
param per 24h. Audit trail captures before/after/reason/trade_ids.

### Atomic write strategy

1. Read `oil_botpattern.json` → dict
2. Compute all proposed nudges for this tick
3. Apply all nudges in-memory to the dict
4. Write to `oil_botpattern.json.tmp` + `os.replace(tmp, original)`
5. Append all nudge records to `oil_botpattern_tune_audit.jsonl`

The atomic write + append-only audit mirrors the sub-system 5 state writer.

### Config (`data/config/oil_botpattern_tune.json`)

```json
{
  "_comment": "Sub-system 6 L1 — bounded auto-tune. Ships with enabled=false.",
  "enabled": false,
  "tick_interval_s": 300,
  "window_size": 20,
  "min_sample": 5,
  "rel_step_max": 0.05,
  "min_rate_limit_hours": 24,
  "bounds": {
    "long_min_edge":                     {"min": 0.35, "max": 0.70, "type": "float"},
    "short_min_edge":                    {"min": 0.55, "max": 0.85, "type": "float"},
    "funding_warn_pct":                  {"min": 0.30, "max": 1.00, "type": "float"},
    "funding_exit_pct":                  {"min": 1.00, "max": 2.50, "type": "float"},
    "short_blocking_catalyst_severity":  {"min": 3,    "max": 5,    "type": "int"}
  },
  "strategy_config_path":   "data/config/oil_botpattern.json",
  "main_journal_jsonl":     "data/research/journal.jsonl",
  "decision_journal_jsonl": "data/strategy/oil_botpattern_journal.jsonl",
  "audit_jsonl":            "data/strategy/oil_botpattern_tune_audit.jsonl",
  "state_json":             "data/strategy/oil_botpattern_tune_state.json"
}
```

### Tier registration

REBALANCE + OPPORTUNISTIC only. NOT in WATCH. Mirrors sub-system 5.

**Rationale:** L1 mutates the config that #5 reads. #5 only runs in
REBALANCE+OPPORTUNISTIC. Running L1 in WATCH would mutate config while the
strategy isn't consuming it — no value, only blast-radius expansion.

### Safety properties

- Ships `enabled: false`. Separate kill switch from sub-system 5's two.
- Hard bounds are clamped in code AND validated at config-load time. A
  config that specifies an out-of-range bound is rejected with a log line.
- Proposed value always `>= bounds.min AND <= bounds.max`. Invariant
  asserted in module tests.
- A single corrupted nudge can at worst shift a param by `rel_step_max`
  (5% of current value). Compounding is bounded by the rate limit and the
  hard bounds.
- Audit trail is append-only and never auto-pruned.
- Atomic write prevents half-written config on crash.

---

## L2 — Reflect proposals

### What it is

A daemon iterator that runs weekly (or first tick after 7 days since last
run). Reads the decision journal + closed trades for the window, looks for
structural patterns — gates that blocked winning setups, thesis conflicts
that cost money, instruments that never produced a profitable trade — and
writes `StructuralProposal` records to a proposals JSONL.

Each proposal has an ID, a type, a human-readable description, the
supporting evidence (trade IDs, decision IDs, counts), and a proposed
action. **No auto-apply.** A Telegram warning alert is emitted listing
the new proposal IDs. Chris reviews via `/selftuneproposals` and taps
`/selftuneapprove <id>` or `/selftunereject <id>`.

### Proposal types (first cut)

| Type | Detection rule | Suggested action |
|---|---|---|
| `gate_overblock` | A specific gate blocked ≥5 decisions in the window, and ≥60% of those blocked trades would have closed in profit based on the next 24h realised price move recorded in the decision journal | Loosen the gate threshold or add an exception condition |
| `gate_underblock` | A specific gate passed ≥5 decisions that resulted in loss, ≥70% loss rate | Tighten the gate threshold |
| `instrument_dead` | An instrument in `instruments` opened ≥3 positions with 0 winners in the window | Consider removing from `instruments` or widening its entry floor |
| `thesis_conflict_frequent` | The thesis_conflict gate fired on ≥3 decisions that would have closed in profit | Reconsider 24h lockout duration or scope |
| `funding_exit_expensive` | Funding-exit closes had avg ROE worse than −1% in the window | Tighten `funding_warn_pct` / `funding_exit_pct` |

All rules ship with minimum sample thresholds so a quiet week produces
zero proposals, not false positives.

### Weekly cadence

Persisted in `data/strategy/oil_botpattern_reflect_state.json`:

```json
{"last_run_at": "2026-04-09T09:00:00+00:00", "last_proposal_id": 0}
```

On each daemon tick, the iterator checks:

```
now - last_run_at >= timedelta(days=7)
```

If false: no-op, return. If true: run, update `last_run_at` atomically.
Missing first run (no state file): seed `last_run_at` to now minus 7 days
so the first meaningful tick triggers it (otherwise first tick fires
immediately on empty state, which is noisy).

### Proposal schema (`data/strategy/oil_botpattern_proposals.jsonl`)

```json
{
  "id": 42,
  "created_at": "2026-04-09T09:00:00+00:00",
  "type": "gate_overblock",
  "description": "Gate 'no_blocking_catalyst' blocked 8 decisions in the last 7 days; 6 of those would have closed in profit based on price 24h later. Consider raising severity floor from 4 to 5.",
  "evidence": {
    "decision_ids": ["BRENTOIL_2026-04-02T...", ...],
    "trade_ids": [],
    "window_days": 7,
    "hits": 8,
    "would_have_won": 6
  },
  "proposed_action": {
    "kind": "config_change",
    "target": "data/config/oil_botpattern.json",
    "path": "short_blocking_catalyst_severity",
    "old_value": 4,
    "new_value": 5
  },
  "status": "pending",
  "reviewed_at": null,
  "reviewed_outcome": null
}
```

`status` transitions: `pending → approved` (via `/selftuneapprove`) or
`pending → rejected` (via `/selftunereject`). On `approved`, the Telegram
handler applies `proposed_action` to the target file atomically and
appends a matching audit record to `oil_botpattern_tune_audit.jsonl`
(source = `reflect_approved` to distinguish from L1 nudges).

### Config (`data/config/oil_botpattern_reflect.json`)

```json
{
  "_comment": "Sub-system 6 L2 — weekly reflect proposals. Ships with enabled=false.",
  "enabled": false,
  "window_days": 7,
  "min_sample_per_rule": 5,
  "min_run_interval_days": 7,
  "main_journal_jsonl":     "data/research/journal.jsonl",
  "decision_journal_jsonl": "data/strategy/oil_botpattern_journal.jsonl",
  "strategy_config_path":   "data/config/oil_botpattern.json",
  "proposals_jsonl":        "data/strategy/oil_botpattern_proposals.jsonl",
  "state_json":             "data/strategy/oil_botpattern_reflect_state.json",
  "audit_jsonl":            "data/strategy/oil_botpattern_tune_audit.jsonl"
}
```

### Tier registration

REBALANCE + OPPORTUNISTIC only. NOT in WATCH. Same reasoning as L1.

---

## Telegram surface

Four new commands, all deterministic (pure code templates, no AI), **no
`ai` suffix**. All four follow the `cli/CLAUDE.md` 5-surface checklist:
handler, HANDLERS dict entry (`/cmd` + bare `cmd`), `_set_telegram_commands`
list, `cmd_help`, `cmd_guide`.

| Command | Purpose |
|---|---|
| `/selftune` | Current L1 state: enabled flag, tunable params with current values + bounds, last nudge per param, last-run timestamp, L2 enabled flag, pending proposal count |
| `/selftuneproposals [N]` | List last N pending proposals from `oil_botpattern_proposals.jsonl`. Default 10. Shows id, type, description, proposed action. |
| `/selftuneapprove <id>` | Mark proposal approved, apply the `proposed_action` to the target file atomically, append audit record, confirm to user. |
| `/selftunereject <id>` | Mark proposal rejected with no file change. Confirm to user. |

Approval + rejection are additive-write operations (not delete) — the
proposal row stays in place with `status` and `reviewed_at` updated via
a rewrite of the JSONL file (load all, mutate, atomic write).

## Testing strategy

Each wedge lands with tests that keep the suite green. Structure:

- `tests/test_oil_botpattern_tune.py` — pure module. Covers bound clamping,
  nudge direction per param type, rate limiting, sample-size gates,
  atomic write, integer vs float param handling.
- `tests/test_oil_botpattern_tune_iterator.py` — iterator. Mocks a
  journal + decision-journal + config, runs tick, verifies written
  config + audit trail. Kill switch test. No nudge when insufficient
  sample. Atomic write survives mid-tick corruption.
- `tests/test_oil_botpattern_reflect.py` — pure module. Each proposal
  type has a positive test (detection fires) and a negative test
  (insufficient sample → no proposal).
- `tests/test_oil_botpattern_reflect_iterator.py` — iterator. Cadence
  check (no-op within 7 days). Proposal write + alert emission. State
  update on run.

Target: every wedge leaves `pytest -x -q` green.

## Wedge breakdown (proposed)

| # | What | Touches trading? | Branch for suite green? |
|---|---|---|---|
| 1 | **This plan doc** — review checkpoint | No | Yes |
| 2 | `data/config/{oil_botpattern_tune,oil_botpattern_reflect}.json` (kill switches OFF) + pre-commit hook allowlist if needed | No | Yes |
| 3 | `modules/oil_botpattern_tune.py` — pure L1 logic + tests | No | Yes |
| 4 | `modules/oil_botpattern_reflect.py` — pure L2 logic + tests | No | Yes |
| 5 | `cli/daemon/iterators/oil_botpattern_tune.py` + tests | Indirectly — mutates #5's config | Yes (iterator ships disabled) |
| 6 | `cli/daemon/iterators/oil_botpattern_reflect.py` + tests | No | Yes |
| 7 | Telegram commands `/selftune`, `/selftuneproposals`, `/selftuneapprove`, `/selftunereject` (5-surface checklist) | Indirectly — approve can mutate #5's config | Yes |
| 8 | `cli/daemon/tiers.py` registration (stash-commit-pop around parallel agent) | No | Yes |
| 9 | Wiki page, build-log entry, `cli/daemon/CLAUDE.md` + top-level `CLAUDE.md` entries, `OIL_BOT_PATTERN_SYSTEM.md` row-6 status flip | No | Yes |

Wedges 1-9 all ship behind `enabled: false`. Sub-system 6 is **not live**
until Chris flips `oil_botpattern_tune.enabled = true` (L1) and/or
`oil_botpattern_reflect.enabled = true` (L2). Neither can do anything until
sub-system 5 itself is enabled and producing closed trades.

**Not in this session:**

- L3 pattern library growth
- L4 shadow trading
- L5 ML overlay (deferred indefinitely)
- `MASTER_PLAN.md` flip (parallel agent holds it unsaved — deferred to
  post-merge alignment)
- Any proportional scaling of the sizing ladder in L1 (structural)

## Out of scope (do NOT pull in)

- Multi-param joint optimisation, bandits, Bayesian search — single-param
  bounded nudges only
- Any ML or LLM-based confidence scoring — parked per SYSTEM doc §6
- Structural changes to sizing ladder rungs — L2 may propose, never
  auto-apply
- Changes to `drawdown_brakes`, kill switches, `instruments`, or any file
  path
- Tuning anything outside `oil_botpattern.json`
- Auto-pruning the audit log (append-only forever, alignment commits
  can archive if the file grows large)

## Spec links

- `OIL_BOT_PATTERN_SYSTEM.md` §6 — L0-L5 contract
- `OIL_BOT_PATTERN_05_STRATEGY_ENGINE.md` — the only writer sub-system 6
  observes, and the sole consumer of the params it nudges
- `modules/oil_botpattern.py` — the live code reading the config
- `cli/daemon/iterators/oil_botpattern.py` — the iterator consuming the
  config on each tick
- `cli/daemon/CLAUDE.md` — tier registration pattern
- `cli/CLAUDE.md` — 5-surface Telegram command checklist
- `data/config/oil_botpattern.json` — the file L1 mutates and L2 may
  propose to mutate
