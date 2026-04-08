# Sub-system 5 — Oil Bot-Pattern Strategy Engine

**Slot in `OIL_BOT_PATTERN_SYSTEM.md`:** row 5. **The ONLY sub-system in
this stack that places trades.** Highest blast radius.

**Status:** APPROVED 2026-04-09 with revisions. Building now.

## REVISIONS after Chris feedback 2026-04-09

The first draft of this plan had per-instrument equity caps and fixed
leverage caps. Chris rejected that framing. The goal is to **compound
wealth as fast as possible without tanking the account** — which means
position size must scale nonlinearly with edge, not be clipped flat.

The revised design:

1. **No equity caps, no leverage caps.** Sizing is conviction-driven
   via a configurable `sizing_ladder` in `oil_botpattern.json`. Higher
   edge → larger notional AND higher leverage. Lower edge → smaller +
   less leverage. This is Druckenmiller-style conviction sizing, per
   `feedback_sizing_and_risk.md`. The ladder is a *norm*, not a cap.

2. **Circuit breakers replace caps.** Instead of per-position equity
   caps, the strategy has drawdown brakes that pause new entries when
   realised/unrealised loss crosses daily / weekly / monthly
   thresholds. This is the "don't tank the account" floor. Defaults:
   3% daily, 8% weekly, 15% monthly — all tunable in config. When a
   brake trips: daily auto-resets at UTC rollover, weekly/monthly
   require manual unpause.

3. **Short-legs grace period: 1 hour** after `enabled=true` is flipped.
   Code-enforced. Chris wants max flex for conditions; 1h is enough to
   smoke-test without sitting on hands for a week.

4. **CL is in the instruments list from day 1.** No hardcoded
   promotion timing. CL gets the same gate chain as BRENTOIL;
   conditions-in-config decide whether it fires. Chris explicitly said
   "depends depends depends" — the plan's original "promote later"
   framing was too simplistic.

5. **No hold-hours cap on longs.** Thesis may hold for years. The long
   leg can roll indefinitely. **Funding cost is the exit trigger, not
   time.** The strategy monitors cumulative funding paid per position
   (via the existing `funding_tracker.jsonl`) and triggers exit when
   funding cost crosses a position-size-proportional threshold. The
   short leg still has a 24h hard cap per SYSTEM doc §4 — that stays.

6. **Closed positions append to the main `journal.jsonl`.** Not a
   separate stream. This means `lesson_author` automatically picks up
   oil_botpattern closes and writes lesson candidates — zero new
   wiring. The per-decision audit log
   (`oil_botpattern_journal.jsonl`) still exists for sub-system 6, but
   it's a *decision* log, not a *trade* log.

Everything below this REVISIONS section reflects the revised design.
The wedge breakdown, gate chain, and coexistence rules stand; only the
sizing and cap sections have changed.

## Conviction sizing ladder (the "norm, not cap" piece)

The strategy sizes every entry via a piecewise ladder keyed off
`edge`, where:

```
edge = blend(classifier_confidence, thesis_conviction, recent_outcome_bias)
```

Components:
- `classifier_confidence` — sub-system 4's `BotPattern.confidence` for
  the instrument, latest record
- `thesis_conviction` — existing `xyz_brentoil_state.json` conviction
  field when direction matches, 0 when it doesn't or when no thesis
- `recent_outcome_bias` — small additive adjustment from the last 5
  closed oil_botpattern trades on this instrument (win rate > 0.6 →
  +0.05, win rate < 0.4 → −0.05, neutral otherwise). Seeds to 0 when
  there's no history.

Edge is clamped to [0, 1]. The ladder translates edge → notional
fraction + leverage:

```json
"sizing_ladder": [
  {"min_edge": 0.50, "base_pct": 0.02, "leverage": 2.0},
  {"min_edge": 0.60, "base_pct": 0.05, "leverage": 3.0},
  {"min_edge": 0.70, "base_pct": 0.10, "leverage": 5.0},
  {"min_edge": 0.80, "base_pct": 0.18, "leverage": 7.0},
  {"min_edge": 0.90, "base_pct": 0.28, "leverage": 10.0}
]
```

`base_pct` = pre-leverage fraction of free equity to commit.
`leverage` = the multiplier applied on top. Target notional at max
conviction (edge ≥ 0.90): 0.28 × 10 = **2.8× equity notional**.
Target at entry floor (edge < 0.50): **zero — no trade**.

The ladder is the default. Chris can flatten or steepen it by editing
`oil_botpattern.json` — no code change needed.

**Why a ladder and not a continuous function:** piecewise is easier to
read in config, easier to journal ("which rung fired"), and easier to
stress-test.

## Circuit breakers (the "don't tank the account" floor)

```json
"drawdown_brakes": {
  "daily_max_loss_pct": 3.0,
  "weekly_max_loss_pct": 8.0,
  "monthly_max_loss_pct": 15.0
}
```

Measured as realised + unrealised on all oil_botpattern positions,
as % of equity at the start of the period.

| Brake | Trip behaviour | Reset |
|---|---|---|
| Daily | Block new entries for rest of UTC day. Existing positions keep running with their stops. | Automatic at UTC midnight |
| Weekly | Pause strategy (no new entries, existing positions honour stops/TPs, force-close on signal). Emit critical alert. | Manual — Chris flips a `brake_cleared_at` timestamp in the state file |
| Monthly | Pause strategy + escalate via heartbeat. Emit critical alert. | Manual — Chris flips a `brake_cleared_at` timestamp in the state file |

These are not per-trade position caps. They're ruin floors.

## Funding-cost exit for longs

Since longs have no hold-time cap (per revision #5), cumulative
funding cost becomes the effective hold-time governor. The strategy
monitors `data/daemon/funding_tracker.jsonl` per position and tracks
cumulative funding paid since entry. When funding crosses either of
these thresholds:

- `funding_warn_pct`: funding paid > 0.5% of position notional → emit
  warning alert, flag in state file. No auto-close.
- `funding_exit_pct`: funding paid > 1.5% of position notional → emit
  `close` OrderIntent. This is an auto-exit.

Both are configurable. These thresholds are chosen to be loose enough
that a strong directional thesis can ride 2-3 weeks on BRENTOIL without
tripping, but tight enough that a grinding sideways market eats the
position before it destroys equity.

The short leg does not use funding-cost exit (it has the 24h hard cap
instead).



## What it is

A daemon iterator that reads outputs from sub-systems 1-4 plus the
existing thesis path and emits `OrderIntent`s tagged
`strategy_id="oil_botpattern"`. Tactical only — every order carries
`intended_hold_hours ≤ 24`. The existing `thesis_engine` +
`xyz_brentoil_state.json` path remains the sole writer for BRENTOIL
positions held > 24h.

This is also where:

- The **scoped short-leg relaxation** for oil lives (the only place in
  the entire codebase where shorting BRENTOIL/CL is legal). Behind hard
  guardrails listed below.
- **CL gets promoted** from `tracked but unsupported` to a real,
  thesis-eligible market.

The strategy engine NEVER bypasses the global SL+TP rule. Every
position it opens immediately enters the existing
`exchange_protection` chain. No exceptions. No special path.

## Why this slot

- Sub-systems 1, 2, 3, 4 are all live and writing to disk. Strategy
  engine has real input streams from day 1.
- It's the first sub-system that writes to `order_queue`, which means
  it's the first that can actually lose money. It needs all four
  upstream signals to make decent decisions.
- It precedes self-tune harness (#6) because #6 has nothing to tune
  until #5 is generating closed trades.

## Inputs (read-only consumers, no new external API calls)

| Source | Purpose |
|---|---|
| `data/research/bot_patterns.jsonl` (#4) | Gate signal: bot_driven_overextension @ conf ≥ 0.7 → short leg eligible |
| `data/heatmap/zones.jsonl` (#3) | Entry/exit price targets — magnet levels |
| `data/heatmap/cascades.jsonl` (#3) | Recent cascades for confirmation |
| `data/supply/state.json` (#2) | Block short legs when fresh supply upgrade present |
| `data/news/catalysts.jsonl` (#1) | Block short legs when high-sev catalyst pending in next 24h |
| `data/thesis/xyz_brentoil_state.json` (existing) | Coexistence — read thesis direction for conflict resolution |
| `TickContext.positions` | Current position state for all instruments |
| `TickContext.prices` | Current mid prices |

The iterator pulls all of these from disk on each tick. No new HTTP
fetches. The polling cost is O(file reads), which is negligible.

## Outputs

| Sink | Purpose |
|---|---|
| `TickContext.order_queue` | OrderIntents tagged `strategy_name="oil_botpattern"` and `meta["intended_hold_hours"] ≤ 24` |
| `data/strategy/oil_botpattern_journal.jsonl` (new) | Per-decision audit log: inputs read, signals scored, action taken, reason |
| `data/strategy/oil_botpattern_state.json` (new) | Per-instrument tactical state: open tactical positions, entry time, hold-hours remaining, realised P&L for daily cap |
| `Alert(severity="warning")` on every short-leg open | Visible in Telegram immediately |

The journal is append-only and is the canonical record for
sub-system 6's auto-tuning loop.

## The scoped short-leg relaxation (CRITICAL READ)

This is the ONLY place in the entire codebase where shorting BRENTOIL
or CL is legal. The relaxation is per-strategy and per-trade. Every
short order MUST satisfy ALL of these conditions, checked in code at
order-emission time, with the failing condition logged:

| Gate | Source | Threshold |
|---|---|---|
| `bot_driven_overextension` classification | `bot_patterns.jsonl` latest record for instrument | confidence ≥ `short_min_confidence` (default 0.7) |
| No high-sev bullish catalyst pending | `catalysts.jsonl` next 24h | NO catalyst with severity ≥ `short_blocking_catalyst_severity` (default 4) and direction in (`up`, `neutral`, missing) |
| No fresh supply disruption upgrade | `supply/state.json` last 72h | `computed_at` is older than `short_blocking_supply_freshness_hours` (default 72) OR no upgrade detected |
| Position size ≤ 50% of long-side budget | `risk_caps.json` | `short_size_ratio_to_long` (default 0.5) × `oil_botpattern.<INST>.max_pct_equity` |
| Hard time-in-trade cap | strategy state | `short_max_hold_hours` (default 24). Force close at cap regardless of P&L. |
| Daily realised loss cap on short layer | strategy state | accumulated realised loss on shorts today ≥ `short_daily_loss_cap_pct` (default 1.5%) of equity → all further shorts blocked for the rest of the day |
| Master kill switch | `oil_botpattern.json` | `short_legs_enabled` (default `false` at first ship). Setting to `false` blocks ALL shorts regardless of other gates. |

**Default at first ship:** `short_legs_enabled = false`. The relaxation
ships disabled. Chris flips it on after watching the long leg run for
≥1 week and reviewing the journal. This is non-negotiable.

All other oil shorting in the rest of the codebase remains forbidden.
This relaxation is `oil_botpattern`-strategy-scoped only.

## Coexistence (writer-conflict resolution)

Per `OIL_BOT_PATTERN_SYSTEM.md` §5 — additive-only with tier ownership.

| Scenario | Resolution |
|---|---|
| Existing BRENTOIL thesis direction = bot-pattern direction | Bot-pattern stacks on top up to its own per-instrument cap. Combined size is checked against `risk_caps.json` total. |
| Existing BRENTOIL thesis direction ≠ bot-pattern direction | Existing long-horizon thesis WINS. Bot-pattern is locked out of BRENTOIL until either (a) thesis flips to flat or (b) 24h elapse from last conflict, whichever first. |
| No thesis (CL) | Bot-pattern is the only writer. CL is now thesis-eligible. |
| Position already open with `strategy_name != "oil_botpattern"` | Bot-pattern does not touch it. Read-only on other strategies' positions. |

The strategy engine identifies its own positions by matching
`strategy_name == "oil_botpattern"` in the position's `meta` field on
read. Positions opened by other paths (manual, thesis_engine,
heatmap-driven AI) are off-limits.

## Per-instrument norms (not caps)

Per Chris revision #1 — **no hard equity caps**. There IS, however, a
per-instrument `atr_buffer_pct` minimum that governs SL placement, and
a per-instrument multiplier on the sizing ladder so CL (less liquid)
takes smaller positions than BRENTOIL at the same edge score.

`data/config/risk_caps.json`:

```json
{
  "oil_botpattern": {
    "BRENTOIL": {
      "sizing_multiplier": 1.0,
      "min_atr_buffer_pct": 1.0,
      "notes": "primary instrument — full sizing ladder"
    },
    "CL": {
      "sizing_multiplier": 0.6,
      "min_atr_buffer_pct": 1.5,
      "notes": "less liquid — 60% of BRENTOIL notional at same edge"
    }
  }
}
```

`sizing_multiplier` applies to `base_pct` from the ladder. Leverage is
untouched per-instrument (the sizing ladder owns leverage). CL at
max edge: 0.28 × 0.6 × 10 = **1.68× equity notional**.

## Configuration

`data/config/oil_botpattern.json`:

```json
{
  "enabled": false,
  "short_legs_enabled": false,
  "instruments": ["BRENTOIL"],
  "tick_interval_s": 60,
  "long_min_confidence": 0.65,
  "short_min_confidence": 0.7,
  "short_blocking_catalyst_severity": 4,
  "short_blocking_supply_freshness_hours": 72,
  "short_size_ratio_to_long": 0.5,
  "short_max_hold_hours": 24,
  "short_daily_loss_cap_pct": 1.5,
  "long_max_hold_hours": 24,
  "intended_hold_hours_default": 12,
  "patterns_jsonl": "data/research/bot_patterns.jsonl",
  "zones_jsonl": "data/heatmap/zones.jsonl",
  "cascades_jsonl": "data/heatmap/cascades.jsonl",
  "supply_state_json": "data/supply/state.json",
  "catalysts_jsonl": "data/news/catalysts.jsonl",
  "risk_caps_json": "data/config/risk_caps.json",
  "thesis_state_path": "data/thesis/xyz_brentoil_state.json",
  "journal_jsonl": "data/strategy/oil_botpattern_journal.jsonl",
  "state_json": "data/strategy/oil_botpattern_state.json"
}
```

**Two kill switches.** `enabled = false` disables the entire iterator.
`short_legs_enabled = false` disables only the short leg. Both ship as
`false`. Chris flips them in order: `enabled` first, then
`short_legs_enabled` after a week of long-leg observation.

`instruments` ships as `["BRENTOIL"]` only. CL is added later — once
sub-system 5 is operating cleanly on BRENTOIL, Chris updates the
config. The plan does NOT auto-promote CL on first ship.

## Tier registration

The new iterator runs in **REBALANCE and OPPORTUNISTIC tiers ONLY**.
NOT in WATCH. This mirrors `execution_engine` and is intentional:

- WATCH is monitor-only. The whole point is no orders.
- Chris currently runs WATCH on mainnet. Therefore sub-system 5 will
  NOT trade in production on first ship. It will sit registered but
  inert until the daemon is promoted to REBALANCE.
- This is a safety feature, not a bug.

## SL + TP enforcement

Every position the strategy opens MUST have both SL and TP on the
exchange. No exceptions. The mechanism is the existing
`exchange_protection` iterator chain — strategy emits the OrderIntent,
the order fills, exchange_protection sees the new position on its next
tick and attaches stops.

The strategy DOES set `meta["preferred_sl_atr_mult"]` and
`meta["preferred_tp_atr_mult"]` so exchange_protection knows the
intended levels for tactical positions (which want tighter stops than
thesis positions). Defaults: SL = 0.8 × ATR, TP = 2.0 × ATR. Per the
direction-rule §4 in CLAUDE.md, every position MUST end up with both
on-exchange — exchange_protection is the enforcer.

If exchange_protection fails to attach a stop (e.g. the trigger order
is rejected), the strategy detects this on its next tick via
`protection_audit` outputs and emits a `close` OrderIntent for the
unprotected position immediately. **An unprotected oil_botpattern
position lives for at most one tick.**

## Telegram surface

Two new commands, both deterministic (no AI, no `ai` suffix):

1. `/oilbot` — current oil_botpattern state: open tactical positions,
   their hold-hours-remaining, today's realised P&L on the strategy,
   short-leg gate status (which gates are passing/failing right now),
   short_legs_enabled flag.
2. `/oilbotjournal [N]` — last N decision records from
   `oil_botpattern_journal.jsonl`. Default 20.

Plus a third command, AI-flavoured:

3. `/oilbotreviewai` — feeds the last week of journal entries to the
   agent and asks for a human-readable review of the strategy's
   behaviour. AI-suffixed because the output is model-authored.

All three follow the 5-surface checklist from `cli/CLAUDE.md`.

## Out of scope (do NOT pull in)

- Self-tuning of any parameter — that's sub-system 6
- New external API calls — strategy reads existing on-disk outputs only
- ML-based confidence — sub-system 4's heuristic is the contract,
  ML overlay is parked (see `project_bot_classifier_ml_revisit.md`)
- Direction-rule changes elsewhere in the codebase — only the
  `oil_botpattern` strategy gets the relaxation, and it's gated by
  `short_legs_enabled` which ships off
- Multi-leg / pair / spread trades on WTI↔Brent spread — interesting
  but a separate plan; v1 trades each instrument independently

## Wedge breakdown (proposed)

This is the order I'd ship in if approved. Each wedge leaves the suite
green and is a separate commit.

| # | What | Touches trading? |
|---|---|---|
| 1 | Plan doc (THIS FILE) — review checkpoint | No |
| 2 | `data/config/{oil_botpattern,risk_caps}.json` (kill switches OFF) + `data/strategy/.gitkeep` + pre-commit hook allowlist | No |
| 3 | `modules/oil_botpattern.py` — pure logic only: input loaders (per-source), gate evaluators (each gate is a pure function returning `(bool, reason)`), entry/exit price computation from zones, journal record dataclass + JSONL I/O, state dataclass + atomic writer | No (still no order placement) |
| 4 | Wedge 3 tests — each gate, journal round-trip, state round-trip, conflict resolution helpers | No |
| 5 | `cli/daemon/iterators/oil_botpattern.py` — daemon iterator. Loads inputs each tick, runs gate chain, decides action, writes journal record, ONLY THEN emits OrderIntent. Critically: write the journal BEFORE the OrderIntent so a crash mid-decision leaves audit evidence. | YES — first wedge that can place orders. Iterator ships disabled by default. |
| 6 | Wedge 5 tests — iterator wiring with mocked inputs and a mock OrderIntent collector. Tests cover: kill switch, both kill switches, gate failures, conflict with thesis, SL/TP meta-fields populated, hold-cap force-close, daily loss cap. | No |
| 7 | `exchange_protection` integration check — verify the SL/TP meta fields are honoured, and the unprotected-position close-immediately path works | YES — touches existing protection code |
| 8 | Telegram commands `/oilbot`, `/oilbotjournal`, `/oilbotreviewai` (5-surface checklist each) | No |
| 9 | Wiki page, build-log entry, CLAUDE.md updates (cli/daemon, cli/, top-level), MASTER_PLAN flip to "1+2+3+4+5 SHIPPED", alignment commit. **CL stays disabled.** **`enabled` stays false.** Chris flips it manually after review. | No |

Wedges 1-9 ship behind the master kill switch. Sub-system 5 is **not
live** until Chris explicitly flips `enabled` and runs the daemon in
REBALANCE tier.

## Chris's answers on the open questions (2026-04-09)

| # | Question | Answer |
|---|---|---|
| 1 | Per-instrument equity cap | **No caps.** Use conviction sizing ladder. |
| 2 | Per-instrument leverage cap | **No caps.** Norms live in the sizing ladder — scale with edge. "Put me under pressure to perform." |
| 3 | Short/long ratio | *(No direct answer; staying with 0.5 default — tunable in config.)* |
| 4 | Short-legs grace period | **1 hour.** Code-enforced. |
| 5 | CL promotion timing | **Depends.** CL is in `instruments` from day 1 with a lower `sizing_multiplier` (0.6). Dynamic gating per-condition, not blanket on/off. |
| 6 | Long hold-hours cap | **No cap.** Thesis may hold for years. Funding cost is the exit trigger — see "Funding-cost exit for longs" section above. |
| 7 | Journal stream | **Shared.** Closed oil_botpattern positions append to the main `journal.jsonl` so `lesson_author` auto-picks them up. The per-decision audit log stays separate. |

## Spec links

- `OIL_BOT_PATTERN_SYSTEM.md` §4 (direction rule), §5 (coexistence), §6 (L0-L5)
- `OIL_BOT_PATTERN_04_BOT_CLASSIFIER.md` — input contract
- `OIL_BOT_PATTERN_03_LIQUIDITY_HEATMAP.md` — input contract
- `OIL_BOT_PATTERN_02_SUPPLY_LEDGER.md` — input contract
- `OIL_BOT_PATTERN_01_NEWS_INGESTION.md` — input contract
- `cli/daemon/iterators/exchange_protection.py` — SL/TP enforcement chain
- `data/config/heatmap.json`, `data/config/bot_classifier.json` — kill-switch convention
