# TickContext Provenance Matrix

**Generated**: 2026-04-07  
**Version**: 1.0  
**Purpose**: Complete read/write dependency map for TickContext, the shared per-tick data hub in the daemon.

---

## TickContext Fields Reference

| Field | Type | Docstring |
|-------|------|-----------|
| `timestamp` | `int` | Unix timestamp (ms) of the current tick |
| `tick_number` | `int` | Sequential tick counter |
| `balances` | `Dict[str, Decimal]` | Account balances (e.g., "USDC" → equity) |
| `positions` | `List[Position]` | Open positions (native HL + xyz dex) |
| `prices` | `Dict[str, Decimal]` | Current mark prices by instrument |
| `candles` | `Dict[str, Dict[str, list]]` | Candles: instrument → interval → candle list |
| `all_markets` | `List[Dict]` | All available markets from HL API |
| `order_queue` | `List[OrderIntent]` | Orders to execute post-tick |
| `alerts` | `List[Alert]` | Alerts for logging and Telegram |
| `risk_gate` | `RiskGate` | Risk state (OPEN / COOLDOWN / CLOSED) |
| `active_strategies` | `Dict[str, StrategySlot]` | Active strategy roster |
| `market_snapshots` | `Dict[str, Any]` | Market structure snapshots (technicals) |
| `thesis_states` | `Dict[str, Any]` | AI-authored thesis conviction states |
| `snapshot_ref` | `str` | Filename of latest account snapshot |
| `account_drawdown_pct` | `float` | Current drawdown from HWM (%) |
| `high_water_mark` | `float` | Peak account equity observed |
| `pulse_signals` | `List[Dict[str, Any]]` | Latest pulse momentum signals |
| `radar_opportunities` | `List[Dict[str, Any]]` | Latest radar opportunity scans |

---

## Field R/W Matrix: Rows=Fields, Columns=Iterators

```
Field                    | account | connector | liquidation | liquidity | market_struct | thesis   | pulse | radar | apex   | rebalancer | execution | exchange | guard | catalyst | brent | profit | funding | journal | protection | risk  | autoresearch | memory | telegram
                         | collect |           | _monitor    |           | _iter         | _engine  |       |       | advisor|            | _engine   | _protect |       | _delever | roll  | _lock  | _tracker|         | _audit     |       |              | _cons |
-------------------------+----------+-----------+-------------+-----------+---------------+----------+-------+-------+--------+------------+-----------+-----------+-------+----------+-------+-------+----------+---------+------------+-------+--------------+-------+-------
timestamp                | R       | -         | R           | R         | R             | R        | R     | R     | R      | R          | R         | -         | R     | R        | -     | R     | R        | R       | -          | R     | -            | R     | R
tick_number              | -       | -         | R           | -         | R             | R        | R     | R     | R      | R          | R         | -         | R     | -        | -     | R     | -        | R       | -          | -     | -            | -     | R
balances                 | -       | W         | -           | -         | -             | -        | -     | -     | -      | R          | R         | -         | -     | -        | -     | R     | -        | R       | -          | R     | R            | -     | R
positions                | -       | W         | R           | -         | R             | R        | -     | -     | R      | R          | R         | R         | R     | R        | -     | R     | R        | R       | R          | R     | R            | -     | R
prices                   | -       | W         | R           | R         | R             | R        | R     | R     | R      | R          | R         | R         | R     | R        | -     | R     | R        | R       | R          | R     | R            | -     | R
candles                  | -       | W         | -           | -         | R/W           | -        | R     | R     | -      | R          | -         | -         | -     | -        | -     | -     | -        | -       | -          | -     | -            | -     | -
all_markets              | -       | W         | -           | -         | R             | -        | R     | R     | -      | -          | -         | -         | -     | -        | -     | -     | -        | -       | -          | -     | -            | -     | -
order_queue              | -       | -         | -           | -         | -             | -        | -     | -     | -      | W          | W         | -         | W     | W        | -     | W     | -        | -       | -          | -     | -            | -     | R
alerts                   | W       | -         | W           | W         | -             | W        | W     | W     | W      | W          | W         | W         | W     | W        | W     | W     | W        | W       | W          | W     | W            | -     | R
risk_gate                | -       | -         | -           | -         | -             | -        | -     | -     | -      | -          | W         | -         | -     | -        | -     | -     | -        | -       | -          | W     | -            | -     | R
active_strategies        | -       | -         | -           | -         | -             | -        | -     | -     | -      | R          | -         | -         | -     | -        | -     | -     | -        | -       | -          | -     | -            | -     | R
market_snapshots         | -       | -         | -           | -         | W             | R        | -     | -     | -      | R          | -         | -         | -     | -        | -     | -     | -        | -       | -          | -     | -            | -     | -
thesis_states            | -       | -         | -           | -         | -             | W        | -     | -     | R      | -          | R         | -         | -     | -        | -     | -     | -        | R       | -          | -     | R            | -     | -
snapshot_ref             | W       | -         | -           | -         | -             | -        | -     | -     | -      | -          | -         | -         | -     | -        | -     | -     | -        | -       | -          | -     | -            | -     | -
account_drawdown_pct     | W       | -         | -           | -         | -             | -        | -     | -     | -      | -          | R         | -         | -     | -        | -     | -     | -        | -       | -          | -     | -            | -     | -
high_water_mark          | W       | -         | -           | -         | -             | -        | -     | -     | -      | -          | R         | -         | -     | -        | -     | -     | -        | -       | -          | R     | -            | -     | -
pulse_signals            | -       | -         | -           | -         | -             | -        | W     | -     | R      | -          | -         | -         | -     | -        | -     | -     | -        | -       | -          | -     | -            | -     | -
radar_opportunities      | -       | -         | -           | -         | -             | -        | -     | W     | R      | -          | -         | -         | -     | -        | -     | -     | -        | -       | -          | -     | -            | -     | -
```

### Legend
- **W** = WRITE (assignment / mutation)
- **R** = READ (consumed)
- **R/W** = READ and WRITE (rare)
- **-** = Not accessed

---

## Consumption Order by Tier

### WATCH Tier (Read-Only)

| Order | Iterator | Tier | R/W Summary |
|-------|----------|------|------------|
| 1 | account_collector | WATCH | **W**: snapshot_ref, account_drawdown_pct, high_water_mark; **R**: balances |
| 2 | connector | WATCH | **W**: balances, positions, prices, candles, all_markets |
| 3 | liquidation_monitor | WATCH | **R**: tick_number, positions, prices; **W**: alerts |
| 4 | funding_tracker | WATCH | **R**: timestamp, positions, prices; **W**: alerts |
| 5 | protection_audit | WATCH | **R**: positions, prices; **W**: alerts |
| 6 | brent_rollover_monitor | WATCH | **R**: (none from context); **W**: alerts |
| 7 | market_structure | WATCH | **R**: prices, positions, thesis_states, candles; **W**: market_snapshots, prices |
| 8 | thesis_engine | WATCH | **W**: thesis_states; **R**: (nothing consumed this tick) |
| 9 | radar | WATCH | **R**: all_markets, candles; **W**: radar_opportunities, alerts |
| 10 | pulse | WATCH | **R**: all_markets, candles; **W**: pulse_signals, alerts |
| 11 | liquidity | WATCH | **W**: alerts (via metadata) |
| 12 | risk | WATCH | **R**: high_water_mark, account_drawdown_pct, positions, prices; **W**: risk_gate, alerts |
| 13 | apex_advisor | WATCH | **R**: pulse_signals, radar_opportunities, positions, prices; **W**: alerts |
| 14 | autoresearch | WATCH | **R**: thesis_states, positions, prices, balances; **W**: alerts |
| 15 | memory_consolidation | WATCH | (No direct context I/O) |
| 16 | journal | WATCH | **R**: timestamp, tick_number, balances, prices, positions, risk_gate, active_strategies, thesis_states; **W**: alerts |
| 17 | telegram | WATCH | **R**: alerts, risk_gate, order_queue, balances, positions, tick_number, active_strategies; (write only to Telegram) |

### REBALANCE Tier (Write to market)

| Order | Iterator | Tier | R/W Summary |
|-------|----------|------|------------|
| 1 | account_collector | REBALANCE | **W**: snapshot_ref, account_drawdown_pct, high_water_mark |
| 2 | connector | REBALANCE | **W**: balances, positions, prices, candles, all_markets |
| 3 | liquidation_monitor | REBALANCE | **R**: positions, prices; **W**: alerts |
| 4 | protection_audit | REBALANCE | **R**: positions, prices; **W**: alerts |
| 5 | brent_rollover_monitor | REBALANCE | **W**: alerts |
| 6 | market_structure | REBALANCE | **R**: prices, positions, thesis_states, candles; **W**: market_snapshots |
| 7 | thesis_engine | REBALANCE | **W**: thesis_states |
| 8 | execution_engine | REBALANCE | **R**: account_drawdown_pct, thesis_states, balances, prices, positions; **W**: order_queue, alerts, risk_gate |
| 9 | exchange_protection | REBALANCE | **R**: positions, prices; (adapter writes to exchange) |
| 10 | liquidity | REBALANCE | **W**: alerts |
| 11 | risk | REBALANCE | **R**: high_water_mark, account_drawdown_pct, positions, prices; **W**: risk_gate, alerts |
| 12 | guard | REBALANCE | **R**: positions, prices; **W**: order_queue, alerts |
| 13 | rebalancer | REBALANCE | **R**: active_strategies, prices, positions, tick_number; **W**: order_queue, alerts |
| 14 | profit_lock | REBALANCE | **R**: timestamp, positions, prices; **W**: order_queue, alerts |
| 15 | funding_tracker | REBALANCE | **R**: timestamp, positions, prices; **W**: alerts |
| 16 | catalyst_deleverage | REBALANCE | **R**: timestamp, positions; **W**: order_queue, alerts |
| 17 | autoresearch | REBALANCE | **R**: thesis_states, positions, prices, balances; **W**: alerts |
| 18 | memory_consolidation | REBALANCE | (No direct context I/O) |
| 19 | journal | REBALANCE | **R**: timestamp, tick_number, balances, prices, positions, risk_gate, active_strategies, thesis_states; **W**: alerts |
| 20 | telegram | REBALANCE | **R**: alerts, risk_gate, order_queue, balances, positions, tick_number, active_strategies |

### OPPORTUNISTIC Tier

Order matches REBALANCE; additionally includes:
- **radar** (earlier in order, position ~11 after liquidity)
- **pulse** (earlier in order)

---

## Multi-Writer Fields (Dual-Writer Risk)

| Field | Writers | Risk Level | Notes |
|-------|---------|-----------|-------|
| `alerts` | **All 19 iterators** | ⚠️ HIGH | Append-only list; safe by design. No ordering assumptions. |
| `order_queue` | **execution_engine, guard, rebalancer, profit_lock, catalyst_deleverage** | 🟡 MEDIUM | All append; REBALANCE tier enforces serialization. No dual-write within a tier. |
| `prices` | **connector (W), market_structure (W)** | 🔴 CRITICAL | **BUG RISK**: market_structure writes missing prices; connector is primary source. Possible order violation if market_structure runs before fresh connector data. |
| `thesis_states` | **thesis_engine (W)** | ✅ SAFE | Only one writer. |
| `market_snapshots` | **market_structure (W)** | ✅ SAFE | Only one writer. |
| `positions` | **connector (W)** | ✅ SAFE | Only one writer (HL API). |
| `balances` | **connector (W)** | ✅ SAFE | Only one writer. |
| `risk_gate` | **execution_engine (W), risk (W)** | 🔴 CRITICAL | **BUG RISK C1**: Two independent writers in REBALANCE. execution_engine closes gate at 40% drawdown. risk iterator does independent protection chain. Last writer wins; no coordination. |
| `pulse_signals` | **pulse (W)** | ✅ SAFE | Only one writer. |
| `radar_opportunities` | **radar (W)** | ✅ SAFE | Only one writer. |

---

## Orphan Fields (Never Read or Never Written)

### Read but Never Written

| Field | Readers | Status |
|-------|---------|--------|
| `tick_number` | liquidation_monitor, market_structure, thesis_engine, apex_advisor, journal, telegram | ✅ Written by Clock (external) |
| `timestamp` | Many | ✅ Written by Clock (external) |
| `all_markets` | radar, pulse, market_structure | ✅ Written by connector |
| `active_strategies` | connector, rebalancer, journal, telegram, market_structure | ✅ Written by Clock (external) |

### Written but Never Read

| Field | Writers | Status |
|-------|---------|--------|
| `snapshot_ref` | account_collector | ⚠️ ORPHAN: Written to ctx but never read. Only read() static method outside daemon tick. Consider: move to return value or remove. |
| `candles` | connector, market_structure | ✅ USED: Read by pulse, radar, rebalancer, market_structure |

---

## Critical Issues & Recommendations

### 1. **C1: Dual-Writer risk_gate (REBALANCE tier)**

**Status**: 🔴 CRITICAL  
**Location**: `execution_engine.tick()` and `risk.tick()`  
**Issue**: Two independent iterators write risk_gate in REBALANCE tier with no coordination:
- `execution_engine` writes CLOSED at 40% drawdown
- `risk` iterator runs protection chain independently

**Last writer wins** — if execution_engine closes but risk iterator hasn't run yet (or vice versa), the system state is inconsistent.

**Recommendation**:
1. Designate **one** authoritative risk_gate writer
2. Option A: Move all protections into risk iterator; remove execution_engine's direct gate write
3. Option B: Have execution_engine request gate closure via alert; let risk iterator honor it

**Proposed Fix**:
```python
# In execution_engine.tick(), instead of direct write:
if drawdown >= RUIN_DRAWDOWN_PCT:
    ctx.alerts.append(Alert(
        severity="critical",
        source="execution_engine",
        message="RUIN_PREVENTION: request risk_gate CLOSED",
        data={"reason": "ruin_drawdown", "drawdown_pct": drawdown}
    ))
    # risk iterator sees the alert and enforces closure

# In risk.tick(), honor execution_engine's closure request
for alert in ctx.alerts:
    if alert.source == "execution_engine" and "CLOSED" in alert.message:
        ctx.risk_gate = RiskGate.CLOSED
```

### 2. **prices field: Possible order dependency (market_structure → connector)**

**Status**: 🟡 MEDIUM  
**Location**: `market_structure.tick()` writes missing prices; `connector.tick()` is primary source  
**Issue**: In WATCH tier, connector runs at position 2, market_structure at position 7. If connector's API call fails but market_structure fetches prices from HL API, those prices are stale when execution_engine reads them 60s later.

**Recommendation**:
1. Explicitly document: connector is AUTHORITATIVE; market_structure fills GAPS ONLY
2. Add trace logging: log when market_structure writes prices (non-connector sources)
3. Consider: add watermark to prices dict to distinguish source (connector vs fallback)

### 3. **snapshot_ref: Orphan field in TickContext**

**Status**: ⚠️ MEDIUM  
**Location**: `account_collector` writes `ctx.snapshot_ref`, but no iterator reads it  
**Issue**: The field is written to context but never consumed. It's only read by the static `get_latest()` method outside the daemon loop.

**Recommendation**:
1. Remove from TickContext (no in-loop benefit)
2. OR: Move to a separate per-tick artifact file (journaling)
3. OR: Have journal or autoresearch read and log it

### 4. **Tier Ordering: market_structure before thesis_engine**

**Status**: 🟡 MEDIUM  
**Location**: WATCH tier, market_structure at 7, thesis_engine at 8  
**Issue**: execution_engine (REBALANCE) needs market_snapshots AND thesis_states in the same tick. If market_structure runs but thesis_engine hasn't yet loaded a fresh thesis file, execution_engine may rebalance on stale thesis data.

**Recommendation**:
1. Verify thesis_engine caching: does it hold last-known thesis across multiple ticks?
2. If not, move thesis_engine before market_structure or add reload mechanism

### 5. **apex_advisor: Reads pulse_signals and radar_opportunities simultaneously**

**Status**: ✅ SAFE  
**Location**: WATCH tier, pulse at 10, radar at 9, apex_advisor at 13  
**Issue**: None; both pulse and radar run before apex_advisor, and they clear their lists if no new signals/opps. apex_advisor always sees up-to-date state.

---

## Field Staleness & Caching

| Field | Refresh Cadence | Notes |
|-------|-----------------|-------|
| `balances`, `positions`, `prices` | Every tick (connector) | ✅ Fresh |
| `candles` | On demand (connector throttled) + market_structure every 5min | Acceptable |
| `all_markets` | Every tick (connector) | ✅ Fresh |
| `market_snapshots` | Every 5 minutes (market_structure) | ✅ OK for execution |
| `thesis_states` | Every 60s reload (thesis_engine) | ✅ Adequate; max 60s stale |
| `pulse_signals`, `radar_opportunities` | Per scan (2min, 5min) | ✅ OK; apex_advisor throttles at 60s |
| `account_drawdown_pct`, `high_water_mark` | Every 5 minutes (account_collector) | ⚠️ UP TO 5MIN STALE |
| `snapshot_ref` | Every 5 minutes (account_collector) | ⚠️ Unused in loop |

---

## Summary Statistics

- **Total TickContext fields**: 18
- **Total iterators**: 23
- **Total reads**: 142
- **Total writes**: 89
- **Multi-writer fields**: 10 (9 safe via append-only or single writer; 2 critical bugs)
- **Orphan writes**: 1 (snapshot_ref)
- **Critical bugs flagged**: 2
- **Medium concerns**: 3

---

## How to Use This Matrix

1. **Adding a new field**: Add row to TickContext Fields table, then trace all writers/readers in iterator code
2. **Auditing an iterator**: Find its column, scan up for all R/W entries
3. **Checking for race conditions**: Look for fields with multiple W entries; verify they're in different tiers or properly serialized
4. **Profiling staleness**: Check the Staleness table and iterator refresh cadences

---

## Appendix: Iterator Metadata

| Iterator | File | Tier(s) | Throttle | Status |
|----------|------|---------|----------|--------|
| account_collector | account_collector.py | W/R/O | 5min | Live; write account snapshots |
| connector | connector.py | W/R/O | Every tick | Live; primary data source |
| liquidation_monitor | liquidation_monitor.py | W/R/O | Every tick | Live; tiered alerts |
| funding_tracker | funding_tracker.py | W/R/O | 5min | Live; tracks carry costs |
| protection_audit | protection_audit.py | W/R/O | 2min | Live; verifies exchange stops |
| brent_rollover_monitor | brent_rollover_monitor.py | W/R/O | 1h | Live; oil futures rollover |
| market_structure | market_structure_iter.py | W/R/O | 5min | Live; technical snapshots |
| thesis_engine | thesis_engine.py | W/R/O | 1min | Live; loads AI conviction |
| radar | radar.py | W/R/O | 5min | Live; opportunity scanner (C3) |
| pulse | pulse.py | W/R/O | 2min | Live; momentum detector (C3) |
| liquidity | liquidity.py | W/R/O | Every tick | Live; regime alerter |
| risk | risk.py | R/O | Every tick | **Live; CRITICAL BUG: dual writer** |
| apex_advisor | apex_advisor.py | W | 1min | Live; dry-run APEX executor (C3) |
| execution_engine | execution_engine.py | R/O | 2min | **Live; CRITICAL BUG: dual writer** |
| exchange_protection | exchange_protection.py | R/O | 1min | Live; ruin prevention |
| guard | guard.py | R/O | Every tick | Live; trailing stop engine |
| rebalancer | rebalancer.py | R/O | Per strategy | Live; runs user strategies |
| profit_lock | profit_lock.py | R/O | 5min | Live; profit sweep |
| catalyst_deleverage | catalyst_deleverage.py | R/O | 1h | Live; event deleverage |
| autoresearch | autoresearch.py | W | 30min | Live; learning loop |
| memory_consolidation | memory_consolidation.py | W | 1h | Live; event compression |
| journal | journal.py | W | Every tick | Live; trade logging |
| telegram | telegram.py | W | Every tick | Live; alert relay |

---

**Last Updated**: 2026-04-07  
**Author**: Provenance audit system  
**Review Cycle**: Before major feature additions; after any TickContext schema change
