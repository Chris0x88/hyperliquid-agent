# Three-Writer Story: Stop-Loss & Exchange State Authority Model

**Status**: Architecture document
**Last Updated**: 2026-04-07 (verified, reconciled with code)
**Context**: C1 dual-writer bug post-mortem and C1' through C7 hardening
**Owner**: Trading bot team

> **Verification status:** Every claim in this doc has been spot-checked against
> source code on 2026-04-07. See `verification-ledger.md` for the audit trail.
> Production currently runs in **WATCH tier**, so most issues flagged below are
> 🟡 LATENT (only fire on tier promotion).

## Executive Summary

The HyperLiquid Bot has three entities that write stop-loss and protection orders to the exchange:

1. **heartbeat** (production, WATCH tier) — standalone launchd process, places ATR-based SL/TP every 2 minutes
2. **exchange_protection** (REBALANCE/OPPORTUNISTIC) — daemon iterator, places ruin-prevention SL only (2% above liq)
3. **execution_engine** (REBALANCE/OPPORTUNISTIC) — daemon iterator, queues sizing orders from thesis conviction

The **C1 bug** happened because both heartbeat and exchange_protection tried to manage the same stop-loss slot concurrently, causing thrashing. This doc explains:
- How the three-writer story now works safely
- The per-asset authority gate and who respects it
- The read-only audit verifier (protection_audit) that prevents silent failures
- The stop-slot ownership matrix showing who owns what in each tier
- Where authority bypasses exist (and whether they're intentional)

## Architecture Overview

### The Three Writers

```
┌─────────────────────────────────────────────────────────────────┐
│                    EXCHANGE (HyperLiquid API)                   │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │  Trigger Orders (Stop-Loss + Take-Profit)               │   │
│  │  Limit Orders (Entries / Exits)                         │   │
│  └──────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────┘
         ↑                    ↑                    ↑
         │ SL (2%)            │ Orders             │ SL (ATR)
    exchange_           execution_            heartbeat
    protection          engine              (external)
    (daemon iter)       (daemon iter)        (launchd)
         │                    │                    │
         └────────┬───────────┴────────┬──────────┘
                  │                    │
              ╔═══════════════════╗  ╔═══════════════════╗
              │ AUTHORITY GATE    │  │ AUDIT VERIFIER    │
              │ (per-asset)       │  │ (read-only)       │
              │ • agent           │  │ • protection_     │
              │ • manual          │  │   audit           │
              │ • off             │  │ • liquidation_    │
              ╚═══════════════════╝  │   monitor         │
                                     ╚═══════════════════╝
```

### Tier Activation

| Writer | WATCH | REBALANCE | OPPORTUNISTIC |
|--------|-------|-----------|---------------|
| **heartbeat** | ✅ enabled | ⚠️ MUST disable | ⚠️ MUST disable |
| **exchange_protection** | ❌ NOT in tier | ✅ active | ✅ active |
| **execution_engine** | ❌ NOT in tier | ✅ active | ✅ active |
| **protection_audit** | ✅ reads only | ✅ reads only | ✅ reads only |

**Critical rule**: heartbeat and exchange_protection cannot run simultaneously. They will race on the same SL slot and thrash orders. When promoting WATCH → REBALANCE, always disable heartbeat launchd job first.

---

## 1. Per-Writer Responsibilities

### 1.1 heartbeat (Separate Process)

**File**: `common/heartbeat.py`  
**Activation**: Runs every 2 minutes via launchd (not a daemon iterator)  
**Tier**: WATCH only (when running at all)  
**Authority checks**: ✅ YES

#### What it writes:
- **Stop-loss (SL)**: ATR-based, `entry ± (3 × ATR)`, respects min-distance and liq buffer
- **Take-profit (TP)**: Thesis-driven or mechanical 5x ATR from entry
- **Order type**: Trigger orders (conditional exchange orders)
- **Instruments**: Any position with `is_watched(coin) = true`

#### Authority checks:
```python
# heartbeat.py:667-671
if not is_watched(coin):
    log.debug("Skipping %s — authority: off", coin)
    continue

asset_authority = get_authority(coin)  # Returns: "agent", "manual", or "off"
```

#### When it places stops:
- Every tick (2 min), for every open position that lacks a stop
- Only if `atr_val > 0` and `not has_stop`
- Skips positions where `authority = "off"`
- Places on both `authority = "agent"` and `authority = "manual"` (safety net)

#### When it exits positions:
- Spike/dip profit-taking: **only if** `authority = "agent"` (lines 866, 917)
- Dip-add scaling: **only if** `authority = "agent"` (lines 994, 1007)
- Stop-loss trigger execution: handled by exchange

#### Risk: Authority gate on entries/exits is asymmetric
- **Stop placement**: respects `is_watched()`, acts on all non-`off`
- **Profit-taking**: requires `authority = "agent"`
- **Result**: A `manual` position can have a stop placed but cannot be auto-exited for profit — asymmetric but safe

---

### 1.2 exchange_protection (REBALANCE/OPPORTUNISTIC Daemon Iterator)

**File**: `cli/daemon/iterators/exchange_protection.py`  
**Activation**: REBALANCE tier and above  
**Authority checks**: ❌ **NO AUTHORITY CHECK** ⚠️

#### What it writes:
- **Stop-loss only**: Ruin prevention, `liq_price × 1.02` (2% buffer above liq)
- **NO take-profit orders**: Exits are conviction-driven via execution_engine
- **Order type**: Trigger orders (conditional exchange orders)
- **Instruments**: **All positions in ctx.positions** (no filtering)

#### How it works:
1. Every 60 seconds, iterates `ctx.positions`
2. For each position with `net_qty ≠ 0`:
   - Calculates target SL = `liq_px × 1.02` (long) or `liq_px × 0.98` (short)
   - Checks if existing SL drifted >0.5% from target
   - Cancels old SL, places new one
3. When position closes, cancels the SL

#### ⚠️ CRITICAL: No authority gate
```python
# exchange_protection.py:96-114
for pos in ctx.positions:
    if pos.net_qty != ZERO:
        active[pos.instrument] = pos

# ... then for each position:
for inst, pos in active.items():
    self._protect_position(inst, pos, ctx)  # NO authority check
```

**This is a BUG**: `exchange_protection` should check `is_agent_managed(inst)` before placing any stop. Currently it will place SLs on `manual` and `off` assets in REBALANCE tier.

#### Comparison to heartbeat:
- **heartbeat**: SL is ATR-based (market-informed), acts as safety net on all positions
- **exchange_protection**: SL is liq-only (ruin prevention), but lacks authority gate

---

### 1.3 execution_engine (REBALANCE/OPPORTUNISTIC Daemon Iterator)

**File**: `cli/daemon/iterators/execution_engine.py`  
**Activation**: REBALANCE tier and above  
**Authority checks**: ❌ **INDIRECT — via thesis_states** ⚠️

#### What it writes:
- **Entries**: Buy/sell orders when conviction band > 0
- **Exits**: Close orders when conviction band = 0 or ruin threshold hit
- **Leverage & sizing**: Per Druckenmiller conviction bands
- **Order type**: Limit or market (via OrderIntent)

#### How it works:
1. Every 2 minutes, iterates `ctx.thesis_states.items()`
2. For each `(market, ThesisState)` in the dict:
   - Calculates conviction → target size & leverage
   - Compares to current position
   - If delta > 5% threshold, queues OrderIntent
3. Iterators cannot add markets to `thesis_states` themselves

#### Authority check (indirect):
```python
# execution_engine.py:130-131
for market, thesis in ctx.thesis_states.items():
    self._process_market(market, thesis, ctx)
```

**How authority is respected**:
- The **thesis_engine** iterator (layer 1) loads thesis files from disk into `ctx.thesis_states`
- AI scheduled task writes thesis only for markets where AI has authority (via delegation)
- If a market is not in `ctx.thesis_states`, execution_engine will never touch it

**But**: There is no explicit `is_agent_managed(market)` check in execution_engine. It trusts that thesis_states is already filtered. If a thesis file somehow gets created for a `manual` asset, execution_engine **will trade it**.

#### Defense-in-depth:
The real gate is in the OrderIntent → adapter flow:
1. `execution_engine` queues OrderIntent
2. `clock._execute_orders()` submits to adapter
3. Adapter's `place_order()` (currently) has no per-asset authority check

**Result**: Execution_engine can trade any market in thesis_states, even if authority is wrong. **This is a gap.**

---

## 2. Authority Gate Implementation

### 2.1 The Authority File

**Location**: `data/authority.json`

```json
{
  "default": "manual",
  "assets": {
    "BTC": {"authority": "agent", "changed_at": "2026-04-07T...", "note": "..."},
    "GOLD": {"authority": "manual", "changed_at": "2026-04-06T...", "note": "User holds"},
    "BRENTOIL": {"authority": "off", "changed_at": "...", "note": "Inactive"}
  }
}
```

### 2.2 Authority Levels

| Level | Meaning | Bot behavior |
|-------|---------|--------------|
| **agent** | Bot owns this asset | Bot can open, close, scale, set SL/TP |
| **manual** | User owns, bot is safety net | Bot can set SL/TP only; cannot enter or exit for profit |
| **off** | Not watched at all | Bot ignores completely; no alerts, no stops |

### 2.3 API Surface

**File**: `common/authority.py`

```python
get_authority(asset: str) -> str          # Returns "agent", "manual", or "off"
is_agent_managed(asset: str) -> bool      # Returns True iff authority == "agent"
is_watched(asset: str) -> bool            # Returns True iff authority != "off"
delegate(asset: str, note: str) -> str    # Set to "agent"
reclaim(asset: str, note: str) -> str     # Set to "manual"
set_authority(asset: str, level: str)     # Direct set
```

### 2.4 Who Actually Calls the Authority Gate

#### ✅ heartbeat (respects it)
- Checks `is_watched()` before any action
- Checks `get_authority()` before profit-taking or dip-adding
- Places SL/TP on all non-`off` assets (both `agent` and `manual`)

#### ❌ exchange_protection (ignores it)
- **No authority check at all**
- Places SL on every position regardless of delegation
- **BUG**: Should check `is_agent_managed()` before placing

#### ⚠️ execution_engine (trusts thesis_states)
- No explicit check
- Implicitly filtered via thesis_states contents
- **GAP**: Should have explicit `is_agent_managed(market)` check before queuing OrderIntent

#### ✅ protection_audit (respects it by design)
- Read-only verifier, no writes
- Audits all positions (reads from exchange, not authority)
- But doesn't alert about authority mismatches

#### ✅ Telegram bot (respects it)
- Displays authority status via `/authority`
- Prevents manual delegation when daemon has authority

---

## 3. Protection Audit (Read-Only Verifier)

### 3.1 Purpose

**File**: `cli/daemon/iterators/protection_audit.py`

The **C1' solution**: Instead of adding a second writer (exchange_protection to WATCH), we added a second reader. Protection_audit verifies heartbeat's work without writing to the exchange.

### 3.2 What it reads
- Fetches all open trigger orders from exchange for main wallet (native + xyz dex)
- Filters to stop-loss orders only (ignores TP orders)
- Matches them to positions in `ctx.positions`

### 3.3 What it verifies (every 120 seconds)

For each open position:

| Check | Alert | Severity |
|-------|-------|----------|
| Position has NO matching stop on exchange | `no_stop` | CRITICAL |
| Stop exists but on wrong side of entry | `wrong_side` | CRITICAL |
| Stop is <0.5% from mark (hunted price) | `too_close` | WARNING |
| Stop is >50% from mark (ineffective) | `too_far` | WARNING |
| Stop now within valid range (was previously flagged) | `ok` | INFO |

### 3.4 What it logs

- All alerts are tagged `severity: critical|warning|info`
- Logs to `ctx.alerts` (picked up by telegram)
- Keeps per-coin state to avoid alert spam
- Only re-alerts if state changes

### 3.5 What it does NOT do

- Never calls `place_trigger_order()`
- Never cancels or modifies stops
- Never executes trades
- Purely observational

### 3.6 Race protection

Protection_audit runs every 120 seconds (heartbeat's cadence). If heartbeat fails or is delayed, protection_audit will surface it as `no_stop` CRITICAL within 2 minutes.

**Tier coverage:** `protection_audit` is active in **all three tiers** (WATCH,
REBALANCE, OPPORTUNISTIC) per `cli/daemon/tiers.py`. In WATCH it verifies heartbeat.
In REBALANCE/OPPORTUNISTIC it verifies `exchange_protection`. The same verifier
catches gaps regardless of which writer is supposed to be active.

---

## 4. Stop-Slot Ownership Matrix

This is the diagram that would have prevented the C1 bug. It answers: **For each tier, who owns the right to place/manage the stop-loss slot?**

### WATCH Tier

```
Position: [LONG BTC @ $40k]

┌─────────────────────────────────────────────────┐
│ Stop-Loss Slot (1 per position)                 │
│                                                 │
│  Owner: heartbeat (external process)            │
│  Updater: heartbeat every 2 minutes             │
│  Verifier: protection_audit every 2 minutes     │
│  Formula: ATR-based                             │
│                                                 │
│  ╔════════════════════════════════════════╗     │
│  ║ Real Order: TRIGGER SELL @ $38,500     ║     │
│  ║ (3x ATR below entry, with constraints) ║     │
│  ╚════════════════════════════════════════╝     │
└─────────────────────────────────────────────────┘

exchange_protection: NOT IN THIS TIER
execution_engine: NOT IN THIS TIER
```

**Rules**:
- Heartbeat places/updates SL every 2 min
- Protection_audit reads every 2 min, alerts if missing or wrong
- Neither exchange_protection nor execution_engine run
- No coordination needed (only one writer)

---

### REBALANCE Tier

```
Position: [LONG BTC @ $40k]

┌─────────────────────────────────────────────────┐
│ Stop-Loss Slot (1 per position)                 │
│                                                 │
│  Owner: exchange_protection (daemon)            │
│  Updater: exchange_protection every 60 sec      │
│  Verifier: protection_audit every 120 sec       │
│  Formula: Liq-based (2% above liq)              │
│                                                 │
│  ╔════════════════════════════════════════╗     │
│  ║ Real Order: TRIGGER SELL @ $35,000     ║     │
│  ║ (2% above liquidation price)           ║     │
│  ╚════════════════════════════════════════╝     │
└─────────────────────────────────────────────────┘

heartbeat: DISABLED (launchd job must be stopped)
protection_audit: reads, alerts if stops missing/wrong
execution_engine: can close position on conviction exit (via order queue)
```

**Rules**:
- Exchange_protection owns the SL slot
- Heartbeat **must be disabled** (would fight exchange_protection)
- Protection_audit monitors that SLs are in place
- If exchange_protection fails, protection_audit will alert within 2 min
- Execution_engine can trigger a position close (conviction exit), which also cancels the SL

**Potential race**: execution_engine closes position → SL auto-cancels, then exchange_protection tries to update SL for closed position. Handled by exchange_protection's cleanup logic (`closed = [inst for inst in self._tracked if inst not in active]`).

---

### OPPORTUNISTIC Tier

```
Position: [LONG BTC @ $40k]

┌─────────────────────────────────────────────────┐
│ Stop-Loss Slot (1 per position)                 │
│                                                 │
│  Owner: exchange_protection + guard             │
│  Updater: exchange_protection (60s), guard (10s)│
│  Verifier: protection_audit (120s)              │
│  Formula: Liq-based + trailing stops (guard)    │
│                                                 │
│  ╔════════════════════════════════════════╗     │
│  ║ Real Order: TRIGGER SELL @ $36,000     ║     │
│  ║ (exchange_protection base + guard tier)║     │
│  ╚════════════════════════════════════════╝     │
└─────────────────────────────────────────────────┘

heartbeat: DISABLED
protection_audit: reads, alerts
execution_engine: can entry/exit on conviction
guard: ratchets stop upward as ROE grows (trailing stop)
```

**Rules**:
- exchange_protection sets base SL (ruin prevention)
- guard module wraps and ratchets it (trailing stops at tiers)
- Protection_audit monitors overall stop validity
- Execution_engine entries/exits via thesis conviction
- All three (exchange_protection, guard, execution_engine) can trigger position closure

---

## 5. Race Conditions & Authority Bypasses

### 5.1 Identified Issues

#### ❌ Issue #1: exchange_protection lacks authority gate

**Status:** 🟡 **LATENT-REBALANCE** — `exchange_protection` is not in
`tiers.py['watch']`, so this gap is dormant in production WATCH. It activates the
moment the daemon is promoted to REBALANCE or OPPORTUNISTIC.

**File**: `cli/daemon/iterators/exchange_protection.py:96-114`

```python
# NO AUTHORITY CHECK
for pos in ctx.positions:
    if pos.net_qty != ZERO:
        active[pos.instrument] = pos

for inst, pos in active.items():
    self._protect_position(inst, pos, ctx)  # Will place SL on ANY asset
```

**Impact**: 
- In REBALANCE tier, exchange_protection will place SLs on `manual` and `off` assets
- This is against the tier model (REBALANCE should only act on delegated assets)
- **Severity**: Medium (SL is protective, not harmful, but violates permission model)

**Fix**: Add before `self._protect_position()`:
```python
from common.authority import is_agent_managed
if not is_agent_managed(inst):
    continue  # Skip non-delegated assets
```

---

#### ⚠️ Issue #2: execution_engine lacks explicit authority check

**Status:** 🟡 **LATENT-REBALANCE** — `execution_engine` only runs in REBALANCE+ tiers
and only acts on markets present in `ctx.thesis_states`. Thesis files are AI-written
under delegation, so this is theoretical unless someone manually creates a thesis
file for a non-delegated asset. Still worth a defensive check.

**File**: `cli/daemon/iterators/execution_engine.py:130-131`

```python
# Trusts that thesis_states is pre-filtered
for market, thesis in ctx.thesis_states.items():
    self._process_market(market, thesis, ctx)
```

**Implicit gate**: Only works on markets in `ctx.thesis_states`, which is populated by thesis_engine (which loads AI-created files).

**Risk**: 
- If a thesis file is manually created for a `manual` asset, execution_engine will trade it
- No explicit `is_agent_managed(market)` call before queueing OrderIntent
- **Severity**: Low (would require manual file creation and delegation config to both be wrong)

**Defense**: 
- Thesis files should only be in `data/thesis/` for AI-delegated markets
- But no explicit code enforcement

**Fix**: Add explicit check in `_process_market()`:
```python
from common.authority import is_agent_managed
if not is_agent_managed(market):
    log.warning("ExecutionEngine skipping %s — not delegated", market)
    return
```

---

#### ⚠️ Issue #3: Clock._execute_orders() has no per-asset authority check

**Status:** 🟡 **LATENT-REBALANCE** — `_execute_orders` only drains the order queue
when other iterators have queued OrderIntents. In WATCH no iterator queues orders
(none are write-capable), so this defense-in-depth gap is dormant. It only matters
in REBALANCE+ if Issues #1/#2 leak through.

**File**: `cli/daemon/clock.py:215-273`

```python
def _execute_orders(self, ctx: TickContext) -> None:
    """Drain order queue and submit to exchange."""
    # ... risk gate checks ...
    for intent in ctx.order_queue:
        # NO authority check on intent.instrument
        self._submit_order(intent)
```

**Risk**: If an OrderIntent somehow makes it to the queue for a non-delegated asset, nothing stops it.

**Severity**: Low (execution_engine is the main enqueuer, so issue #2 would catch it first)

**Defense-in-depth**: 
- execution_engine should pre-filter (per issue #2)
- But OrderIntent could come from other iterators (guard, rebalancer) that also lack checks

---

#### ✅ heartbeat + exchange_protection coordination (solved)

**Issue**: Both writers managing the same SL slot (the C1 bug)

**Solution**: 
- heartbeat runs only in WATCH tier
- exchange_protection runs only in REBALANCE+ tier
- They never run simultaneously
- The docs explicitly say "disable heartbeat launchd when promoting to REBALANCE"

**Safeguard**: Protection_audit detects if heartbeat goes silent (no stop placed) and alerts CRITICAL.

---

### 5.2 Authority Bypass Routes

#### Route 1: Thesis file + REBALANCE tier

```
Create: data/thesis/manual_asset.json with conviction=0.8
Result: execution_engine will trade the asset
Detection: Only if protection_audit or human notices
```

**Likelihood**: Low (requires intentional file creation)  
**Prevention**: Enforce thesis_engine to check `is_agent_managed()` before loading

#### Route 2: Direct OrderIntent queue

```
Iterator X calls: ctx.order_queue.append(OrderIntent(instrument="GOLD"))
If GOLD is manual: still executes
Detection: Logs + Telegram alert (journal iterator), but too late
```

**Likelihood**: Low (no iterator currently does this)  
**Prevention**: Guard iterator could check authority before queueing

---

## 6. Summary of Authority Checks

### Checklist: Per-Writer Authority Enforcement

| Component | Check | Where? | Gap? |
|-----------|-------|--------|------|
| **heartbeat** | `is_watched()` + `get_authority()` | Lines 667-671 | ✅ No (complete) |
| **exchange_protection** | NONE | N/A | ❌ YES (place SL on all) |
| **execution_engine** | Implicit (thesis_states) | Context | ⚠️ YES (no explicit check) |
| **guard** | NONE on order queue | N/A | ⚠️ YES (could queue on manual) |
| **rebalancer** | NONE visible | N/A | ⚠️ YES (unknown) |
| **clock** | NONE | `_execute_orders()` | ⚠️ YES (no per-asset check) |
| **protection_audit** | N/A (read-only) | N/A | ✅ No |

### Recommendations

1. **CRITICAL**: Add authority check to `exchange_protection.py` before `_protect_position()`
2. **HIGH**: Add explicit `is_agent_managed()` check in `execution_engine._process_market()`
3. **HIGH**: Add per-asset authority check in `clock._execute_orders()` as fallback
4. **MEDIUM**: Document that thesis files should only exist for delegated assets
5. **MEDIUM**: Add authority check to guard before order queueing
6. **LOW**: Update this doc when changes are made

---

## 7. Appendix: Code References

| Concept | File | Lines |
|---------|------|-------|
| Tier definitions | `cli/daemon/tiers.py` | 1–80 |
| Heartbeat main | `common/heartbeat.py` | 1–50, 650–850 |
| Exchange protection | `cli/daemon/iterators/exchange_protection.py` | 54–180 |
| Execution engine | `cli/daemon/iterators/execution_engine.py` | 84–293 |
| Protection audit | `cli/daemon/iterators/protection_audit.py` | 66–343 |
| Authority gate | `common/authority.py` | 47–101 |
| Clock/order execution | `cli/daemon/clock.py` | 215–273 |
| Thesis engine | `cli/daemon/iterators/thesis_engine.py` | 32–120 |

---

## 8. Mermaid: Three-Writer Flow Diagram

```mermaid
graph TB
    subgraph Exchange["Exchange (HyperLiquid)"]
        SL["Trigger Orders (SL)"]
        Orders["Limit/Market Orders"]
    end

    subgraph Daemon["Daemon (Tick Loop)"]
        TE["thesis_engine (Layer 1)"]
        EE["execution_engine"]
        EP["exchange_protection"]
        PA["protection_audit"]
        GU["guard"]
        CL["clock"]
    end

    subgraph External["External Process"]
        HB["heartbeat"]
    end

    subgraph Auth["Authority & Audit"]
        AG["authority.py<br/>(per-asset gate)"]
        TS["thesis_states<br/>(AI conviction)"]
    end

    HB -->|"place_trigger_order<br/>(SL/TP)"| SL
    EP -->|"place_trigger_order<br/>(2% liq SL)"| SL
    GU -->|"sync_exchange_sl<br/>(trailing SL)"| SL
    EE -->|"queues OrderIntent"| CL
    CL -->|"place_order<br/>(entries/exits)"| Orders
    PA -->|"_fetch_all_triggers<br/>(read-only)"| SL
    TE -->|"loads thesis files"| TS
    EE -->|"reads markets from"| TS
    HB -.->|"should check"| AG
    EP -.->|"NO CHECK!"| AG
    EE -.->|"indirect via TS"| AG
    
    style HB fill:#ff9999
    style EP fill:#ffcc99
    style EE fill:#99ccff
    style PA fill:#99ff99
    style AG fill:#ff99ff
    style TS fill:#ffff99
```

---

## 9. Related Documents

- `docs/wiki/operations/tiers.md` — Tier promotion checklist and WATCH/REBALANCE/OPPORTUNISTIC details
- `docs/wiki/components/daemon.md` — Daemon architecture and tick loop
- `cli/daemon/context.py` — TickContext definition and order queue
- `common/thesis.py` — ThesisState model

---

**Last reviewed**: 2026-04-07  
**Next review**: Post authority-gate fixes (gap #1 and #2)
