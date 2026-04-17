# Power Law BTC — "savings account" allocation strategy

> **NOT FINANCIAL ADVICE.** This document describes the design intent of a
> personal trading strategy implemented in this codebase. It is a worldview
> and a methodology, not a recommendation. It describes what the system
> *does*, not what *you* should do. Past behaviour of any market does not
> guarantee future behaviour. Bitcoin can lose substantial value rapidly.
> Use of this software is at your own risk.

## What problem this strategy is designed to solve

A holder who believes Bitcoin is a long-horizon store-of-value but does
**not** want to:

- Time the market (chase pumps, panic-sell drawdowns).
- Sit through the full volatility of 100% BTC exposure.
- Park cash earning ~nothing in a bank deposit account that loses
  purchasing power to inflation.

…wants something between **"all cash"** and **"all BTC"** that
*mechanically* dials exposure based on where price sits on a long-run
trend, taking emotion out of the entry/exit decision.

## The design intent in one paragraph

The Power Law BTC strategy is built for a **mixed USD + BTC wallet** where
the BTC allocation percentage is determined **only** by Bitcoin's position
relative to its long-term power-law trend (the "Heartbeat Model"). When
price is far below trend (cheap by the model's lens), the system holds a
larger BTC allocation. When price is far above trend (expensive by the
model's lens), the system reduces BTC and holds more USD. The intent is
to **capture upside without forcing the operator to chase the market**,
and to **automatically take chips off the table when the model says
extreme**, leaving a USD-heavy posture during euphoria and a BTC-heavy
posture during fear. By construction, this should produce a **lower
volatility and shallower drawdown** profile than a static buy-and-hold
position, while still participating in the long-term trend the model
believes in.

The framing the operator uses is: **a savings account that owns Bitcoin
through the cycle, sized rationally rather than emotionally**. The goal
is to be a *credible alternative to leaving cash in a bank deposit
account*, not to outperform aggressive traders. Capital preservation
during regime extremes is the design priority; lifting the long-run
return above cash deposit yields is the secondary aim.

## What the system actually does (mechanics, not promises)

- **Inputs**: BTC spot price, the operator-configured power-law trend
  parameters (floor + cycle ceiling), and a `max_leverage` cap on the
  perp position.
- **Output**: a target BTC allocation as a percentage of the wallet's
  notional, evaluated on a fixed cadence (hourly by default).
- **Mapping**: `target_leverage = (allocation_pct / 100) × max_leverage`
  on BTC-PERP. The strategy rebalances the position toward this target
  on each tick.
- **Re-evaluation**: every tick re-reads price and recomputes; no
  discretionary overrides.
- **Rebalancing**: when `allocation_pct` falls (price moved up the trend
  channel), the strategy reduces position size — i.e., *cashes some out
  into USD*. When `allocation_pct` rises (price moved down the channel),
  the strategy adds back exposure.

The strategy is intentionally simple. It has no view on news, no
discretionary catalysts, no thesis files. It is one input, one output,
on a clock.

## What this strategy is *not*

- Not a market-timing system that calls tops or bottoms.
- Not a trading strategy in the active sense — it's a **rebalancer**.
- Not optimised for outperformance vs spot Bitcoin in a single bull run.
  In an unbroken upward move, mechanically trimming exposure as price
  rises will *underperform* a static long. The point is the *behaviour
  through a full cycle*, not any single leg of it.
- Not a substitute for the operator's judgment in genuine regime change.
  If the model itself becomes invalidated (e.g., Bitcoin's long-run
  trend fundamentally breaks), the model needs to be retired or
  re-parameterised — the strategy will not tell you that.

## Where the code lives

| Component | Location |
|---|---|
| Pluggable model + bot | `plugins/power_law/` |
| Strategy wrapper | `strategies/power_law_btc.py` |
| Roster slot | `data/daemon/roster.json` (currently `paused: true, simulate: true`) |

The strategy is a registered plugin in the daemon roster but ships in
**simulate** mode by default — operator must explicitly unpause and
remove the simulate flag before any real orders are placed.

## Author's worldview that the code encodes

Written so future Claude sessions (or future-you) understand the
*intent*, not just the surface mechanics:

1. **Bitcoin's long-run trend is real, but its medium-term volatility
   is unbearable for most savers.** The power-law model is one lens for
   that long-run trend.
2. **Most people lose money on Bitcoin by chasing it up and selling it
   down.** A mechanical rebalancer removes the option to do either.
3. **A wallet that mechanically holds USD when BTC is rich and BTC when
   it's cheap should, over a cycle, give an operator a sleep-at-night
   alternative to cash deposits.**
4. **The system is a tool, not a promise.** It can be wrong; the model
   can break. Loss is possible. The operator carries the risk, the
   system just executes the rebalance discipline.

## Disclaimers (load-bearing)

- This is **not financial advice**. It is a description of code that the
  operator wrote for personal use.
- This is **not a recommendation** to allocate any portion of a portfolio
  to Bitcoin or to use this strategy.
- **Past behaviour** of Bitcoin or the power-law trend **does not predict
  future behaviour**. The trend can break.
- The operator's wallet **can lose value, including total loss**, when
  using leveraged perp positions. Liquidation is possible if margin
  conditions deteriorate.
- The safety floors in the rest of this codebase (per-position
  liquidation cushion alerts, portfolio risk monitor, exchange-side
  SL+TP enforcement) reduce but do not eliminate the risk of loss.
- Anyone reading this and considering similar code for their own use:
  **consult a licensed financial advisor in your jurisdiction**, do
  your own research, and understand that this software is provided
  AS-IS with no warranty.
