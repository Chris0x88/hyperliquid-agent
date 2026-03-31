# Implementation Plan: HyperLiquid Agent Harness Hardening

**Goal:** Transform the agent into a maximally autonomous, reliable brokerage copilot that makes as much money as possible without getting wiped out.

**Guiding Principles (from research):**
- Binary Autonomy: AI is ON (full trust within risk rails) or OFF
- All sizing uses ACCOUNT equity, not position margin
- Funding cost is always-present carry — can't buy-and-hold forever
- Design all AI-facing output for a "dumb head" (StepFun 3.5, ~150k usable tokens)
- Never regress the 6 account-level bugs already fixed

---

## Phase 1: Foundation Hardening (Middleware, Logging, Telemetry)

These are low-risk, high-value changes that improve every other phase.

### [NEW] `common/middleware.py` — Iterator Middleware Chain

Wraps every daemon iterator and heartbeat sub-function with consistent:
- Entry/exit timing
- Structured error capture (no more ad-hoc try/except)
- Per-iterator timeout budget (10s default, configurable)

```python
# Core pattern
def run_with_middleware(name, fn, ctx, timeout_s=10):
    start = time.monotonic()
    try:
        with timeout(timeout_s):
            result = fn(ctx)
        elapsed = time.monotonic() - start
        log.info("[done] %s (%.1fs)", name, elapsed)
        ctx.telemetry.record(name, elapsed, "ok")
        return result
    except TimeoutError:
        elapsed = time.monotonic() - start
        log.warning("[timeout] %s after %.1fs", name, elapsed)
        ctx.telemetry.record(name, elapsed, "timeout")
    except Exception as e:
        elapsed = time.monotonic() - start
        log.error("[error] %s: %s", name, e)
        ctx.telemetry.record(name, elapsed, "error", str(e))
```

### [NEW] `common/trajectory.py` — Session Trajectory Logger

Writes a JSONL file per daemon/heartbeat session:
```
logs/trajectory_2026-04-01_0830.jsonl
```
Each line: `{"ts": ..., "component": "heartbeat", "action": "stop_placed", "symbol": "BRENTOIL", "details": {...}}`

Replaces nothing — additive. Existing SQLite `action_log` stays.

### [NEW] `common/telemetry.py` — Behavioral Telemetry

Tracks per-heartbeat-cycle:
- Cycle duration (alert if >5min)
- API call count + failure rate
- Stop placement success/failure rate
- Funding cost accumulated this cycle

Writes to `state/telemetry.json` — overwritten each cycle.

### [MODIFY] `cli/daemon/clock.py`

Wire middleware around each iterator call in `_tick()`.

### [MODIFY] `scripts/run_heartbeat.py`

Wire trajectory logger around the heartbeat run.

---

## Phase 2: Event-Driven Engine (The "Missed Drop" Fix)

### [NEW] `common/event_watcher.py` — WebSocket Price Monitor

Async process that connects to HyperLiquid WebSocket feed and watches for:
- Flash dips (>3% in 10 min)
- Volume surges (5x average)
- Funding rate flips

When triggered → runs `ConsolidationDetector` → writes event file → sends Telegram alert.

### [NEW] `common/consolidation.py` — Consolidation Detector

Multi-phase algorithm (from refined analysis):
1. Detect dip via existing `detect_spike_or_dip()`
2. Watch for volume decline + range compression + no second leg down
3. After 3 sideways 1-min candles → emit `BUY_SIGNAL`
4. If price breaks below dip low → `ABORT`
5. If no consolidation in 15 min → `TIMEOUT`

### [MODIFY] `common/heartbeat.py`

Wire consolidation detector between dip detection and the existing `dip_add` safety guards.
Add laddered entry (40/30/30 split) instead of single market order.

### Preservation Rules

> [!CAUTION]
> These existing safety guards MUST be preserved in the dip-add flow:
> - `dip_add_min_liq_pct: 12%` — minimum liquidation distance
> - `dip_add_max_drawdown_pct: 3%` — max daily drawdown to allow add
> - `dip_add_cooldown_min: 120` — max one add per 2h
> - `account_risk_adjusted_escalation()` — don't panic on small positions
> - `total_equity = native + xyz + spot_usdc` — NEVER use position margin

---

## Phase 3: AI Interface (Design for Dumb Head)

### [MODIFY] `scripts/scheduled_check.py`

Add dual output:
1. **Full JSON** (existing) — for Claude/Gemini ad-hoc analysis
2. **Digest summary** (new) — 500 tokens max, human-readable:

```
📊 Account: $1,160 total ($770 main + $390 vault)
📈 Positions: BRENTOIL 3x long (+$12.40, +1.6%), BTC vault (+$3.20)
⚡ Funding: BRENTOIL -0.002% (you're getting paid), BTC +0.008% (costing $0.31/day)
🔔 Alerts: None
📝 Thesis: BRENTOIL bullish 0.8 conviction (5 days old, effective 0.78)
```

### [MODIFY] `openclaw/IDENTITY.md`

Update from "petroleum-informed oil & crypto" to multi-market agent.

### [MODIFY] `openclaw/SOUL.md`

Update to reference current multi-market capabilities, heartbeat system, and event-driven triggers.

### [MODIFY] `openclaw/HEARTBEAT.md`

Wire to actual `run_heartbeat.py` system (currently empty placeholder).

### [NEW] `openclaw/MEMORY.md`

AI-readable summary of current agent state, updated by reflector/scheduled_check:
- Current positions and thesis states
- Recent significant events
- Open questions for the user
- Last heartbeat status

---

## Phase 4: Account Hardening

### [MODIFY] `cli/risk_monitor.py`

Remove hardcoded `ADDR` and `VAULT`. Load from credential system:
```python
# Before (broken for any other user):
ADDR = "0x80B5801ce295C4D469F4C0C2e7E17bd84dF0F205"

# After (works for anyone):
ADDR = resolve_key("HL_MAIN_WALLET") 
```

### [MODIFY] `common/heartbeat.py`

Same — replace `VAULT_ADDRESS` and `MAIN_ACCOUNT` constants with credential resolution.

### [NEW] `common/funding_tracker.py` — Cumulative Funding Cost

Tracks total funding paid/received per position over time:
```python
@dataclass
class FundingAccumulator:
    symbol: str
    total_paid: float = 0.0      # Negative = received
    hours_held: int = 0
    avg_hourly_cost: float = 0.0
    
    def record_hour(self, funding_rate: float, position_notional: float):
        cost = position_notional * funding_rate
        self.total_paid += cost
        self.hours_held += 1
        self.avg_hourly_cost = self.total_paid / self.hours_held
```

This feeds into thesis re-evaluation: "This BRENTOIL position has cost $14.30 in funding over 12 days."

---

## Verification Plan

### Automated Tests
- All existing 77 test files must pass: `pytest tests/`
- New tests for: `middleware.py`, `trajectory.py`, `consolidation.py`, `funding_tracker.py`
- Integration test: simulated 3% dip → consolidation → laddered entry flow

### Manual Verification
- Run heartbeat cycle and verify trajectory JSONL output
- Verify telemetry.json updates each cycle
- Check `scheduled_check.py` produces both JSON and digest outputs
- Confirm hardcoded addresses are replaced and credential resolution works
- Run the OpenClaw copilot and verify it can orient from the digest summary

---

## Open Questions

> [!IMPORTANT]
> 1. **WebSocket source:** Should the EventWatcher connect directly to HyperLiquid's WebSocket API, or use a third-party aggregator? Direct is faster but needs reconnection logic.
> 2. **Phase ordering:** Should we start with Phase 1 (foundation) or Phase 2 (event-driven) first? Phase 1 is safer but Phase 2 is higher immediate value.
> 3. **Funding tracker granularity:** Track per-hour (matches HL settlement) or per-heartbeat-cycle (every 2 min)? Per-hour is simpler, per-cycle catches more.
