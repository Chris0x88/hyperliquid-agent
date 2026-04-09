# oil_botpattern self-tune harness (sub-system 6)

**Runs in:** REBALANCE, OPPORTUNISTIC (NOT WATCH — same reasoning as #5)
**Sources:**
- `cli/daemon/iterators/oil_botpattern_tune.py` — L1 bounded auto-tune iterator
- `cli/daemon/iterators/oil_botpattern_reflect.py` — L2 weekly reflect proposals iterator
- `modules/oil_botpattern_tune.py` — L1 pure logic
- `modules/oil_botpattern_reflect.py` — L2 pure logic

**Spec:** `docs/plans/OIL_BOT_PATTERN_06_SELF_TUNE_HARNESS.md`
**Parent spec:** `docs/plans/OIL_BOT_PATTERN_SYSTEM.md` §6

## Purpose

Sub-system 6 wraps sub-system 5 with a bounded self-improvement loop. It's
the "Chris is tired of directing" layer — the bot learns from its own
closed trades and nudges params within hard safety bounds, then once a
week it surfaces structural change proposals to Telegram for human review.

The harness is the first sub-system in the stack that does NOT place
trades. It mutates the config that sub-system 5 reads on its next tick.

## Layer ladder (from SYSTEM doc §6)

| Layer | What it does | Cadence | Human | Status |
|---|---|---|---|---|
| L0 | Hard contracts (tests, SL+TP, JSON schemas) | per commit/tick | none | **shipped** (pre-existing infra) |
| L1 | Bounded auto-tune — journal-replay nudges params within hard bounds after each closed trade | per closed trade | none | **shipped** |
| L2 | Reflect proposals — weekly structural change proposals to Telegram with 1-tap promote/reject | weekly digest | 1-tap | **shipped** |
| L3 | Pattern library growth — detects novel bot-pattern signatures in `bot_patterns.jsonl` and emits candidates for 1-tap promotion | per new pattern | 1-tap | **shipped** |
| L4 | Shadow counterfactual — replays approved L2 proposals against the last N days of decisions and reports divergences + est. PnL delta | per approved proposal | none | **shipped** |
| L5 | ML overlay | — | — | deferred indefinitely (≥100 closed trades required) |

Contract (SYSTEM doc §6, non-negotiable):

> The system is allowed to LEARN automatically. The system is not allowed
> to CHANGE STRUCTURE without one human tap.

L1 LEARNS param values. L2 PROPOSES structural changes but never applies
them — approval is always a manual Telegram tap.

## Kill switches (both ship OFF)

1. `data/config/oil_botpattern_tune.json → enabled: false` — L1 auto-tune iterator
2. `data/config/oil_botpattern_reflect.json → enabled: false` — L2 reflect iterator

Both are independent of sub-system 5's kill switches. The harness can be
flipped on without affecting #5 (it just has nothing to tune until #5
produces closed trades).

## L1 — bounded auto-tune

### Tunable param whitelist

Defined in `modules/oil_botpattern_tune.TUNABLE_PARAMS`:

| Param | Type | Default bounds | Nudge heuristic |
|---|---|---|---|
| `long_min_edge` | float | 0.35–0.70 | `long_winrate > 0.60 → −`, `< 0.40 → +` |
| `short_min_edge` | float | 0.55–0.85 | same, on short leg |
| `funding_warn_pct` | float | 0.30–1.00 | ≥30% of longs close on funding loss → tighten; 0% + ≥7d avg hold → loosen |
| `funding_exit_pct` | float | 1.00–2.50 | same, but loose side requires ≥14d avg hold; forced ≥ warn + 0.5 |
| `short_blocking_catalyst_severity` | int | 3–5 | short_avg_roe < 0 + blocks < 2 → tighten; short_avg_roe > 0 + blocks ≥ 3 → loosen |

### What is NOT tunable (structural)

- `enabled`, `short_legs_enabled`, `instruments` — ownership stays with Chris
- `drawdown_brakes.*` — ruin floor, structural safety
- `short_max_hold_hours` — hard safety cap
- `sizing_ladder[*]` rungs — L2 may propose, L1 never touches
- File paths
- `preferred_sl_atr_mult`, `preferred_tp_atr_mult` — exchange_protection contract

### Nudge discipline

- `rel_step_max` (default 5%) — a single nudge can only shift a param by
  at most 5% of its current value (or ±1 for integer params)
- `min_rate_limit_hours` (default 24) — per-param rate limit
- `min_sample` (default 5) — minimum per-direction sample before any nudge
- Every nudge clamped to hard bounds by `ParamBound.clamp()` before write
- Invariant: `funding_exit_pct ≥ funding_warn_pct + 0.5`

### Audit trail

Every nudge appends a record to
`data/strategy/oil_botpattern_tune_audit.jsonl`:

```json
{
  "applied_at": "2026-04-09T10:00:00+00:00",
  "param": "long_min_edge",
  "old_value": 0.50,
  "new_value": 0.475,
  "reason": "long winrate 70% over 10 trades → loosen entry floor",
  "stats_sample_size": 10,
  "stats_snapshot": {...},
  "trade_ids_considered": ["L0", "L1", ...],
  "source": "l1_auto_tune"
}
```

Audit log is append-only. `source` is `l1_auto_tune` for automatic nudges
and `reflect_approved` for L2 proposals applied via `/selftuneapprove`.

### Config path reference

`data/config/oil_botpattern_tune.json`:

```json
{
  "enabled": false,
  "tick_interval_s": 300,
  "window_size": 20,
  "min_sample": 5,
  "rel_step_max": 0.05,
  "min_rate_limit_hours": 24,
  "bounds": { ... },
  "strategy_config_path":   "data/config/oil_botpattern.json",
  "main_journal_jsonl":     "data/research/journal.jsonl",
  "decision_journal_jsonl": "data/strategy/oil_botpattern_journal.jsonl",
  "audit_jsonl":            "data/strategy/oil_botpattern_tune_audit.jsonl",
  "state_json":             "data/strategy/oil_botpattern_tune_state.json"
}
```

## L2 — weekly reflect proposals

### Cadence

Fires on the first tick where `now - last_run_at ≥ min_run_interval_days`
(default 7). State persisted in
`data/strategy/oil_botpattern_reflect_state.json`:

```json
{"last_run_at": "2026-04-09T09:00:00+00:00", "last_proposal_id": 42}
```

Missing state file → first tick fires immediately, then throttles for 7d.

### Detection rules

| Type | Fires when |
|---|---|
| `gate_overblock` | A gate blocked ≥`min_sample` decisions in the window |
| `instrument_dead` | An instrument had ≥`min_sample` trades with 0 winners |
| `thesis_conflict_frequent` | thesis_conflict gate fired ≥`min_sample` times |
| `funding_exit_expensive` | ≥`min_sample` funding-cost exits with avg ROE worse than −1% |

Each rule ships with a minimum sample threshold so a quiet week emits
zero proposals, not false positives.

### Proposal lifecycle

1. L2 iterator detects pattern → appends `StructuralProposal` record to
   `data/strategy/oil_botpattern_proposals.jsonl` with `status="pending"`
2. Telegram warning alert fires listing new proposal IDs
3. Chris runs `/selftuneproposals` to review
4. Chris taps `/selftuneapprove <id>` or `/selftunereject <id>`
5. On approve: the `proposed_action` is applied atomically to the target
   file AND a `reflect_approved` record is appended to the L1 audit log
6. Proposal record is rewritten with `status="approved"|"rejected"` +
   `reviewed_at` + `reviewed_outcome`

**L2 never auto-applies anything.** Every structural change needs a tap.

### Config path reference

`data/config/oil_botpattern_reflect.json`:

```json
{
  "enabled": false,
  "window_days": 7,
  "min_sample_per_rule": 5,
  "min_run_interval_days": 7,
  ...
}
```

## Telegram surface

Four deterministic commands (no `ai` suffix — all code-generated output):

| Command | Purpose |
|---|---|
| `/selftune` | Current L1 + L2 state: kill switches, tunable params with current values + bounds, last 5 nudges, pending proposal count |
| `/selftuneproposals [N]` | List pending proposals (default 10, max 25) |
| `/selftuneapprove <id>` | Apply a pending proposal's `proposed_action` atomically and mark approved |
| `/selftunereject <id>` | Mark a pending proposal rejected (no file change) |

## Coexistence with sub-system 5

- L1 mutates `oil_botpattern.json`. Sub-system 5 reloads this file on
  every tick via `_reload_config()`, so nudges take effect on the next
  `oil_botpattern` tick.
- L1 writes a new config atomically (`tmp + os.replace`). Mid-write
  crashes leave the old file intact.
- L1 ignores non-`oil_botpattern` trades in the main journal. Sub-system
  5 is the only writer the harness observes.
- L2 proposals target `oil_botpattern.json` (or other files explicitly
  named in `proposed_action.target`). On approval the `path` key is
  rewritten atomically.
- Neither L1 nor L2 touches `enabled`, `short_legs_enabled`,
  `instruments`, or `drawdown_brakes` under any circumstances.

## Blast radius

- L1: with both kill switches off, zero effect. With L1 on but #5 off,
  zero effect (nothing closes, nothing to tune).
- L1: with L1 on AND #5 on, worst-case per-param drift is bounded by
  `rel_step_max` × `24h rate limit` × hard bounds. A single runaway
  run-loop can shift a float param by at most ~5% before being rate-
  limited for 24h, and can never exceed its declared bounds.
- L2: never applies anything. Worst case is noisy Telegram alerts.
- Approve handler: applies the exact `proposed_action` in the proposal
  record. Only `kind="config_change"` is auto-applicable; `kind="advisory"`
  is marked approved but no file changes.

## L3 — pattern library growth

### What it is

A daemon iterator that watches `data/research/bot_patterns.jsonl` and
detects NOVEL `(classification, direction, confidence_band, signals)`
signature tuples that are not already in the live catalog. When a
signature crosses `min_occurrences` in the window, it is emitted as a
`PatternCandidate` to `data/research/bot_pattern_candidates.jsonl`.

Chris reviews via `/patterncatalog` and promotes with
`/patternpromote <id>` (writes to the live catalog) or discards with
`/patternreject <id>` (catalog untouched).

### Signature computation

- **classification** — from sub-system 4's output
- **direction** — "up" | "down" | "flat"
- **confidence_band** — confidence rounded to the nearest
  `confidence_band_precision` (default 0.1), so 0.73 and 0.77 collapse
  into the same bucket at 0.70/0.80 respectively
- **signals_sig** — the sorted `|`-joined unique signals list; empty
  signals → `∅`

Two bot-pattern rows with the same signature are equivalent for
library-growth purposes.

### Kill switch + tier

`data/config/oil_botpattern_patternlib.json → enabled: false`. Ships
disabled.

Registered in **all three tiers** (unlike L1/L2/L4). Reason: L3 is
read-only against `bot_patterns.jsonl` and write-only to its own
files — it does not mutate any config, does not affect sub-system 5,
does not trade. Safe in WATCH where catalog growth still has value
even without live trading.

### Classifier integration

**L3 does NOT modify sub-system 4's classifier behavior in this
wedge.** Promoted catalog entries are purely observational. A future
wedge can teach sub-system 4 to gate classifications on the promoted
live catalog.

## L4 — shadow counterfactual evaluation

### What it is

A look-back counterfactual replay that answers "over the last N days
of closed trades + decisions, how would the proposed param change
have performed?" Given an approved L2 proposal, the iterator:

1. Loads the recent decision + closed-trade window
2. Re-runs the affected gate (e.g. `long_min_edge` threshold check,
   `short_blocking_catalyst_severity` severity floor replay) with the
   PROPOSED param value
3. Counts how many decisions would have had the same outcome, how
   many would have diverged (newly entered or newly skipped)
4. Estimates a first-order PnL delta using the window's average
   trade PnL
5. Appends a `ShadowEval` record to
   `data/strategy/oil_botpattern_shadow_evals.jsonl` and attaches a
   `shadow_eval` sub-field to the proposal record

### Counterfactual rules (first-wedge coverage)

| Param | Rule |
|---|---|
| `long_min_edge`, `short_min_edge` | Edge-threshold replay: was `edge >= current` vs `edge >= proposed` |
| `short_blocking_catalyst_severity` | Severity-floor replay: parses `sevN` from the gate's reason string and compares `sev >= current_floor` vs `sev >= proposed_floor` |

Other params (funding_warn_pct, funding_exit_pct) are not auto-
evaluable in this wedge — they're flagged with
`shadow_eval.status = "not_applicable"` so the iterator doesn't retry
them every tick.

### Not paper trading

This wedge is a LOOK-BACK counterfactual, not a forward paper
executor. The SYSTEM doc §6 describes L4 as "run in shadow (paper)
mode for ≥N closed trades before being eligible for promotion", which
is the forward-paper reading. The counterfactual look-back gives the
same signal (does the proposed change improve outcomes?) using the
data we already have, without needing a parallel mock executor. A
future wedge can add a forward paper executor on top.

### Kill switch + tier

`data/config/oil_botpattern_shadow.json → enabled: false`. Ships
disabled.

Registered in REBALANCE + OPPORTUNISTIC only. Same reasoning as
L1/L2: no value when no trades are closing.

## Deferred (future wedges)

- **L3 classifier integration.** Teach sub-system 4 to gate its
  classification on the live promoted catalog. Separate wedge.
- **L4 forward paper executor.** Run the strategy with proposed params
  against live market data in a mock executor (no real orders), as
  originally described by SYSTEM doc §6. Builds on the counterfactual
  look-back.
- **L5 — ML overlay.** Deferred indefinitely per SYSTEM doc §6.
  Requires ≥100 closed oil_botpattern trades before re-evaluation.

## Test coverage

- `tests/test_oil_botpattern_tune.py` — L1 pure module (41 tests)
- `tests/test_oil_botpattern_tune_iterator.py` — L1 iterator (13 tests)
- `tests/test_oil_botpattern_reflect.py` — L2 pure module (22 tests)
- `tests/test_oil_botpattern_reflect_iterator.py` — L2 iterator (12 tests)
- `tests/test_telegram_selftune_commands.py` — L1/L2 Telegram commands (16 tests)
- `tests/test_oil_botpattern_patternlib.py` — L3 pure module (24 tests)
- `tests/test_oil_botpattern_patternlib_iterator.py` — L3 iterator (12 tests)
- `tests/test_telegram_patternlib_commands.py` — L3 Telegram commands (13 tests)
- `tests/test_oil_botpattern_shadow.py` — L4 pure module (19 tests)
- `tests/test_oil_botpattern_shadow_iterator.py` — L4 iterator (10 tests)
- `tests/test_telegram_shadow_command.py` — L4 Telegram command (9 tests)

Total: 191 tests covering the harness (L1–L4).
