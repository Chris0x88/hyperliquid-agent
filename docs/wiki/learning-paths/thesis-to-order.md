# Learning Path: Thesis -> Order

How a thesis file drives position sizing and order placement. Read these files in order.

---

## 1. `common/thesis.py` -- ThesisState dataclass

**Start here.** This is the contract between the AI (writer) and the daemon (reader).

Key fields on `ThesisState` (line ~57):

- `market` -- e.g. `"xyz:BRENTOIL"` or `"BTC-PERP"`
- `direction` -- `"long"` | `"short"` | `"flat"`
- `conviction` -- 0.0-1.0 (Druckenmiller bands)
- `thesis_summary` -- human-readable thesis
- `invalidation_conditions` -- list of strings (NOT price levels)
- `recommended_leverage`, `recommended_size_pct`, `weekend_leverage_cap`
- `take_profit_price` -- thesis-based TP, None = no TP
- `last_evaluation_ts` -- unix ms when AI last evaluated

Staleness tiers (`effective_conviction()`, line ~110):
- `needs_review` -- >24h. Triggers Telegram reminder, no conviction change.
- `is_stale` -- >7d. Linear taper from full conviction toward 0.3.
- `is_very_stale` -- >14d. Clamp to 0.3 (defensive).

File layout on disk: `data/thesis/{market_slug}_state.json`

---

## 2. `cli/daemon/context.py` -- TickContext + Iterator Protocol + OrderIntent

**The bus everything rides on.**

- `TickContext` (line ~97) -- shared data bag for the tick. Every iterator reads from and writes to this struct.
  - `prices`, `positions`, `balances`, `total_equity` -- populated by connector
  - `market_snapshots` -- populated by market_structure
  - `thesis_states` -- populated by thesis_engine
  - `order_queue: List[OrderIntent]` -- populated by execution_engine, drained by clock
  - `risk_gate` -- OPEN / COOLDOWN / CLOSED
  - `alerts` -- fire-and-forget notification queue

- `OrderIntent` (line ~39) -- the order struct. Fields: `strategy_name`, `instrument`, `action` (buy/sell/close/noop), `size`, `price`, `reduce_only`, `order_type`, `state` (Nautilus FSM).

- `Iterator` Protocol (line ~162) -- every iterator implements `tick(ctx)`, `on_start(ctx)`, `on_stop()`.

---

## 3. `cli/daemon/iterators/connector.py` -- Data source

**First iterator to run every tick.** Populates:
- `ctx.prices` -- live mid prices from HyperLiquid
- `ctx.positions` -- open positions (native + xyz)
- `ctx.balances` -- USDC balances
- `ctx.total_equity` -- native + xyz + spot USDC (the true account value)
- `ctx.all_markets` -- full universe metadata

Handles the `xyz:` prefix normalization issue: the xyz clearinghouse returns names WITH `xyz:` prefix, native does NOT. Connector normalizes both forms.

---

## 4. `cli/daemon/iterators/market_structure_iter.py` -- Technicals

Computes ATR, signal summaries, and technical indicators for every watched market. Populates `ctx.market_snapshots` (dict of `MarketSnapshot` keyed by market name).

Downstream consumers (execution_engine, exchange_protection) rely on ATR for stop placement and sizing.

---

## 5. `cli/daemon/iterators/thesis_engine.py` -- Thesis loader

Reads thesis JSON files from `data/thesis/`, deserializes into `ThesisState` objects, applies staleness taper via `effective_conviction()`, and writes the result to `ctx.thesis_states`.

This is the bridge between the AI layer (which writes JSON files via scheduled tasks) and the mechanical execution layer.

---

## 6. `cli/daemon/iterators/execution_engine.py` -- THE KEY FILE

**Where conviction becomes orders.** This iterator:

1. Reads `ctx.thesis_states` for each market
2. Reads conviction from `ThesisState.conviction` (0.0–1.0) and `recommended_leverage`
3. Computes target position size: conviction x recommended_size_pct x equity x leverage
4. Compares target vs current position (from `ctx.positions`)
5. Emits `OrderIntent` objects to `ctx.order_queue`

Kill switch: `conviction_bands.enabled = false` in config.

Only runs at REBALANCE tier and above (not WATCH).

---

## 7. `cli/daemon/iterators/exchange_protection.py` -- Mandatory SL/TP

Reads `ctx.positions` and ensures every open position has both a stop-loss and take-profit on the exchange. This is the ruin floor.

- SL: ATR-based (reads from `ctx.market_snapshots`)
- TP: from `thesis.take_profit_price` if set, otherwise mechanical 5x ATR
- Places/adjusts trigger orders on HyperLiquid

Only runs at REBALANCE tier and above.

---

## 8. `cli/daemon/clock.py` -- Main loop + order submission

The tick engine. Key section: `_execute_orders()` (lines ~217-305).

Order submission flow:
1. Check `ctx.order_queue` is non-empty
2. If `risk_gate == CLOSED` -- drop all orders
3. If `risk_gate == COOLDOWN` -- allow reduce-only, skip new entries
4. Per-asset authority check via `is_agent_managed()` -- last defense-in-depth gate
5. If mock mode: log only. If live: call `_submit_order()` which hits the HL adapter
6. Clear queue after processing

The clock also manages `HealthWindow` (error budget / circuit breaker), tick timing, and iterator lifecycle.

---

## 9. `cli/daemon/tiers.py` -- Iterator activation by tier

**Which iterators run at which tier:**

| Tier | Key iterators |
|------|--------------|
| WATCH | connector, market_structure, thesis_engine, all oil subsystems (shadow mode), risk, telegram |
| REBALANCE | everything in WATCH + **execution_engine** + **exchange_protection** + guard + rebalancer + profit_lock |
| OPPORTUNISTIC | everything in REBALANCE + radar + pulse |

The critical distinction: `execution_engine` and `exchange_protection` only run at REBALANCE+. In WATCH tier, thesis states are computed and orders are proposed but never executed.

---

## Data flow summary

```
data/thesis/*.json          (AI writes)
        |
        v
  thesis_engine.py          (deserialize + staleness taper)
        |
        v
  ctx.thesis_states         (conviction per market)
        |
        v
  execution_engine.py       (conviction bands -> sizing -> OrderIntent)
        |
        v
  ctx.order_queue           (pending orders)
        |
        v
  clock._execute_orders()   (risk gate -> authority check -> HL adapter)
        |
        v
  HyperLiquid exchange      (live order)
        |
        v
  exchange_protection.py    (mandatory SL/TP placed on new positions)
```
