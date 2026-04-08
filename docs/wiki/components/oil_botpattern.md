# oil_botpattern strategy engine

**Runs in:** REBALANCE, OPPORTUNISTIC (NOT WATCH — this iterator places orders)
**Source:** `cli/daemon/iterators/oil_botpattern.py`
**Pure logic:** `modules/oil_botpattern.py`
**Spec:** `docs/plans/OIL_BOT_PATTERN_05_STRATEGY_ENGINE.md`

## Purpose

Sub-system 5 of the Oil Bot-Pattern Strategy. **The only place in the
codebase where shorting BRENTOIL or CL is legal**, behind a chain of
hard gates plus two master kill switches. Conviction-sized
(Druckenmiller-style) with drawdown circuit breakers as the ruin
floor. Funding-cost exit for longs (no time cap); 24h hard cap on
shorts.

Consumes outputs of sub-systems 1-4 + existing thesis + funding
tracker from disk, runs the gate chain, computes sizing from the edge
ladder, and emits OrderIntents tagged `strategy_name="oil_botpattern"`.

## Kill switches (both ship OFF)

1. `data/config/oil_botpattern.json → enabled: false`
   Disables the entire iterator. On first ship this is `false`. Chris
   flips it manually after reviewing the plan.

2. `data/config/oil_botpattern.json → short_legs_enabled: false`
   Disables the short leg specifically. Shorts require this PLUS a
   1-hour grace period after `enabled` was flipped on. On first ship
   this is `false`.

## Inputs (read-only, no new external API calls)

| Source | Purpose |
|---|---|
| `data/research/bot_patterns.jsonl` | Classification + confidence (sub-system 4) |
| `data/heatmap/cascades.jsonl` | Recent cascade context (sub-system 3) |
| `data/supply/state.json` | Short-leg gate (sub-system 2) |
| `data/news/catalysts.jsonl` | Short-leg gate (sub-system 1) |
| `data/thesis/xyz_brentoil_state.json` | Thesis conflict resolution |
| `data/daemon/funding_tracker.jsonl` | Long-leg funding-cost exit |
| `data/research/journal.jsonl` | Recent outcome bias (last 5 closed oil_botpattern trades) |
| `TickContext.balances` / `prices` | Equity + mid prices |

## Outputs

| Sink | Purpose |
|---|---|
| `TickContext.order_queue` | OrderIntents tagged `strategy_name="oil_botpattern"` with SL/TP meta |
| `data/strategy/oil_botpattern_journal.jsonl` | Per-tick decision audit log (opens AND skips) |
| `data/strategy/oil_botpattern_state.json` | Tactical state: open positions, window PnL, brake timestamps, enabled_since |
| `data/research/journal.jsonl` (existing) | Closed positions append here so `lesson_author` auto-picks them up |
| `Alert(severity="warning")` on every short-leg open | Visible in Telegram |

## Conviction sizing ladder

Edge → (base_pct, leverage), with a per-instrument `sizing_multiplier`
from `risk_caps.json`:

| Edge | base_pct | Leverage | Max notional (BRENTOIL, 1.0x mult) |
|---|---|---|---|
| < 0.50 | — | — | **no trade** |
| ≥ 0.50 | 2% | 2× | 4% of equity |
| ≥ 0.60 | 5% | 3× | 15% |
| ≥ 0.70 | 10% | 5× | 50% |
| ≥ 0.80 | 18% | 7× | 126% |
| ≥ 0.90 | 28% | 10× | **280%** (2.8× equity notional) |

`edge = max(classifier_confidence, thesis_conviction_if_direction_matches) + recent_outcome_bias`

The ladder is NOT a cap. It's a norm. Higher edge → bigger position
AND more leverage. Lower edge → smaller + less leverage. This scales
risk to confidence.

CL uses `sizing_multiplier = 0.6` so at max edge it takes 1.68×
equity notional — less than BRENTOIL, reflecting lower liquidity.

## Drawdown circuit breakers (the ruin floor)

Measured as realised PnL on oil_botpattern positions, as % of equity
at the start of the window.

| Brake | Default cap | Reset |
|---|---|---|
| Daily | 3% | Automatic at UTC midnight |
| Weekly | 8% | Manual — Chris flips `brake_cleared_at` |
| Monthly | 15% | Manual — Chris flips `brake_cleared_at` |

When a brake trips: no new entries. Existing positions keep running
with their exchange-attached stops. The daily brake auto-resets at
UTC rollover; weekly/monthly require a manual clear.

These are NOT per-trade equity caps. They're circuit breakers against
ruin, per Chris's "compound wealth fast but don't tank the account".

## Gate chain

Every entry candidate runs through ALL applicable gates. Any failure
blocks the entry and the failure reason is journaled. The chain:

| Gate | Applies to | Passes when... |
|---|---|---|
| `classification` | long + short | Latest BotPattern exists, matches direction, confidence ≥ floor |
| `thesis_conflict` | long + short | No thesis OR thesis flat OR same direction (stacking) |
| `short_grace_period` | short only | ≥1h elapsed since `enabled` flipped on |
| `no_blocking_catalyst` | short only | No pending bullish high-sev catalyst in next 24h |
| `no_fresh_supply_upgrade` | short only | No fresh supply state with active disruptions in last 72h |
| `short_daily_loss_cap` | short only | Daily realised loss < 1.5% of equity |

Longs only go through the first two gates. Shorts go through all six.

Additional always-on gates:
- **Drawdown brakes** evaluated before any entry — if tripped, skip
  the entire entry loop for the tick
- **Master kill switches** — `enabled=false` short-circuits everything;
  `short_legs_enabled=false` skips short direction

## Long-leg funding-cost exit

Since longs have no hold-time cap, the strategy tracks cumulative
funding paid per position against `data/daemon/funding_tracker.jsonl`
and exits when:

- `funding_paid > 0.5%` of notional → warning alert (no auto-close)
- `funding_paid > 1.5%` of notional → auto-close via `close`
  OrderIntent

This makes funding cost the effective hold-time governor for longs.
Strong directional theses can ride 2-3 weeks without tripping; grinding
sideways markets eat the position before it destroys equity.

## Short-leg hard cap

Shorts have a 24h hard cap. Force-close regardless of P&L. This is
non-negotiable per SYSTEM doc §4.

## Coexistence with existing thesis path

Per SYSTEM doc §5:

- **Same direction as thesis** → bot-pattern stacks on top. Sizing
  uses blended edge (classifier + thesis conviction).
- **Opposite direction** → existing long-horizon thesis WINS.
  Bot-pattern is locked out of that instrument for 24h from the last
  conflict timestamp (tracked in-memory per iterator instance).
- **No thesis** (CL) → bot-pattern is the sole writer.

The strategy identifies its own positions by `strategy_name ==
"oil_botpattern"` in the order meta. Positions opened by other paths
are read-only to this iterator.

## SL + TP enforcement

Every OrderIntent carries `preferred_sl_atr_mult` and
`preferred_tp_atr_mult` in meta (defaults 0.8× and 2.0×). The existing
`exchange_protection` iterator sees these on the next tick after fill
and attaches exchange-side SL/TP triggers. Per CLAUDE.md
"every position MUST have both SL and TP on exchange — no exceptions".

## Telegram surface

| Command | Purpose | AI? |
|---|---|---|
| `/oilbot` | Strategy state: kill switches, brakes, open positions, funding | No (deterministic) |
| `/oilbotjournal [N]` | Recent decision records with gate failures | No (deterministic) |
| `/oilbotreviewai [N]` | AI summary of decisions (routes to telegram_agent) | **Yes** — `ai` suffix required |

## Tier registration

Runs in **REBALANCE and OPPORTUNISTIC only**. NOT in WATCH. This
mirrors `execution_engine` and is intentional: WATCH is monitor-only,
so sub-system 5 ships inert on Chris's current mainnet WATCH daemon
until the tier is promoted.

## Tests

- `tests/test_oil_botpattern.py` — pure logic (61 tests): edge blend,
  sizing ladder, all gates, drawdown brakes, window rollover,
  funding-cost exit, short hold cap, decision/state I/O
- `tests/test_oil_botpattern_iterator.py` — iterator wiring (16
  tests): kill switches, long/short entry paths, thesis conflict,
  brake blocking, hold-cap force-close, funding exit, decision
  journaling
- `tests/test_telegram_oil_botpattern_commands.py` — Telegram surface
  (7 tests): kill-switch display, position rendering, journal
  rendering, AI review routing, HANDLERS registration

## First-ship posture

- Master kill switch: **OFF**
- Short legs: **OFF**
- Instruments: `["BRENTOIL", "CL"]` (both, per Chris's "depends depends
  depends")
- Daemon tier: WATCH (current production)
- **Effect: sub-system 5 ships registered but INERT.** It will only
  activate when Chris flips `enabled` in the config AND promotes the
  daemon to REBALANCE tier. Short legs require an additional flip
  PLUS 1h grace period.

See the sub-system 5 plan doc for Chris's answers on cap policy and
the rationale behind no-caps + circuit-breaker-ruin-floor design.
