# Trading System: Middle Office + Autonomous BTC + Memory

**Date:** 2026-03-31
**Status:** Draft (v3 — simplified, realistic)
**Author:** Claude (brainstorming session with Chris)

## Vision

Three simple, independently reliable systems that compose into a financial copilot:

1. **The Code** — algorithms + risk management, runs 24/7, no dependencies
2. **The Memory** — records everything with full execution traces, no dependencies
3. **The AI** — oversight + improvement, enhances when available, nothing breaks when off

## Two Markets, Two Modes

| Market | Mode | Who trades | System's role |
|--------|------|-----------|---------------|
| **xyz:BRENTOIL** | Manual + Middle Office | Chris picks trades | Protect positions: stops, profit-taking, spike/dip detection, stop-hunt defense, liq monitoring, alerts |
| **BTC-PERP** (Vault) | Fully Autonomous | Enhanced Power Law | Trade, manage risk, record, optimize for HL perps fees/funding — full stack testbed |

**All trades and risk actions reported to Telegram (chat_id: 5219304680).**

---

## Relationship to Existing Code

### Schema coexistence

Existing tables (`events`, `learnings`, `summaries`) remain untouched. New tables (`observations`, `action_log`, `execution_traces`) serve different purposes:
- `events` = human/AI-written geopolitical events → keep using via `log_event()`
- `learnings` = human/AI-written lessons → keep using via `log_learning()`
- `observations` = programmatic state snapshots with temporal validity → new, automated
- `action_log` = system actions with reasoning → new, replaces ad-hoc logging

No migration needed. Both old and new tables coexist in the same SQLite DB.

### Risk management coexistence

The existing `RiskManager` + `RiskGate` runs INSIDE the TradingEngine during daemon strategy execution. The heartbeat's escalation runs OUTSIDE the daemon as an independent watchdog. They do not conflict because:
- `RiskManager` gates strategy decisions during tick loop (prevents bad entries)
- Heartbeat audits positions after the fact (adds stops, checks leverage, takes profit)
- If both want to deleverage, the first one to execute succeeds; the second sees the already-reduced leverage and skips
- The heartbeat NEVER places new entries — it only protects and reduces

### GuardBridge coexistence

`GuardBridge` manages trailing stops for positions opened by the daemon. The heartbeat adds stops only when NO stop exists on exchange. Check flow:
1. Heartbeat reads open orders from HL API for the position
2. If any trigger order (stop-loss) exists → skip, respect existing stop
3. If zero stop-loss orders exist → add one at ATR-based level
4. GuardBridge's exchange-level stops are visible to the API → heartbeat sees them and skips

### What the heartbeat adds that RiskManager / GuardBridge DON'T do

The existing risk infrastructure has gaps. Here's what each system handles:

| Concern | RiskManager | GuardBridge | **Heartbeat (new)** |
|---------|:-----------:|:-----------:|:-------------------:|
| Daily drawdown limit | ✅ | — | ✅ (with Telegram alerts) |
| Leverage ratio enforcement | ✅ | — | ✅ (with progressive deleverage) |
| Trailing stops on active trades | — | ✅ | — (defers to Guard) |
| **Stop-loss on ALL positions** | — | Only daemon trades | ✅ **Manual trades too** |
| **Liquidation distance monitoring** | — | — | ✅ **With auto-deleverage** |
| **Profit-taking on spikes** | — | — | ✅ |
| **Stop-hunt detection** | — | — | ✅ |
| **Funding rate cost tracking** | — | — | ✅ |
| **Telegram alerts for everything** | — | — | ✅ |
| **BTC rebalance failure recovery** | — | — | ✅ |
| **Position-exists-without-stop audit** | — | — | ✅ |
| **Cross-market monitoring** | — | — | ✅ (oil + BTC) |

Key gap the heartbeat fills: **Chris's manual oil trades have NO automated protection today.** RiskManager only runs inside the TradingEngine daemon. GuardBridge only wraps daemon-opened positions. If Chris opens a 10x leveraged oil position manually on HyperLiquid and walks away, nothing monitors it. The heartbeat fixes this.

### Market identifier mapping

| Canonical ID | HL API instrument | HL API dex param | Wallet |
|-------------|-------------------|------------------|--------|
| `xyz:BRENTOIL` | `BRENTOIL` | `dex='xyz'` | Main 0x80B5... |
| `BTC-PERP` | `BTC` | (none — default) | Vault 0x9da9... |

The heartbeat maps canonical IDs to the correct API call format. For xyz markets, all API calls pass `dex='xyz'`. This mapping lives in `data/config/market_config.json`.

---

## Phase 1: The Heartbeat (protects money today)

Pure Python. launchd. No AI dependency. No human dependency.

### 1A. Position Auditor (runs every 2 minutes)

Reads all open positions from HyperLiquid API. For each position:

**Stop-loss enforcement:**
- If position has NO stop-loss order on exchange → add one
- ATR calculation: 14-period ATR on 4-hour candles (fetched from HL candle API). Cached for 1 hour (ATR doesn't change fast).
- Stop placement: 3x ATR below average entry price for longs, above for shorts
- "Average entry price" = weighted average from HL account state API (the exchange tracks this natively)
- Never place stop within 2% of current price (avoid noise sweep)
- Never place stop tighter than liquidation price + 3% buffer
- If computed stop is below liq price + 3% → place at liq price + 3% and alert "stop is very tight"
- Telegram: "🛡️ Added stop on BRENTOIL: 20 contracts long, stop @ $103.50 (3x ATR)"

**Profit-taking:**
- If unrealized PnL% > threshold AND position age < time window → take partial profit
- Position age: computed from HL account state `entryTime` field (the exchange tracks this)
- If `entryTime` is unavailable: use first `action_log` entry for this market as fallback, or skip profit-taking check (safe default — no action on missing data)
- Configurable per-market in `data/config/profit_rules.json`
- Telegram: "💰 Took 25% profit on BRENTOIL: 5 contracts @ $113.20 (+5.2% in 22min)"

**Liquidation distance monitor:**
- <10% → Telegram alert (L1)
- <8% → reduce leverage by 1x, minimum floor of 1x (if already 1x, alert only) (L2)
- <5% → reduce leverage to 3x or to current-1x, whichever is lower, minimum floor of 1x (L3)
- Cool-down: L2 max once per 30min, L3 max once per 1h

**Drawdown monitor:**
- "Session peak" = highest account equity since heartbeat first run, stored in `working_state.json` as `session_peak_equity`. Reset daily at 00:00 AEST.
- >5% from session peak → Telegram alert
- >8% → reduce position 25%, alert
- >12% → reduce position 50%, urgent alert

**Funding rate monitor:**
- If hourly funding >0.1% for 3 consecutive periods → alert with daily drag cost
- If cumulative funding drag >1% of position → alert

**Spike/dip detection + stop-hunt defense:**

The heartbeat tracks price movement between cycles (every 2 minutes). On each run, compare current price to last known price (from `working_state.json`).

*Spike detection (profit-taking opportunity):*
- If price moved >2% in Chris's favor since last check → "spike detected"
- If spike >3% in <10 minutes (tracked across consecutive runs) → take 15-25% profit
- Reasoning: fast spikes in oil often reverse. Free money if thesis is intact.
- Telegram: "📈 Spike detected: BRENTOIL +3.2% in 8min. Took 15% profit (4 contracts @ $111.50)"

*Dip detection (potential add opportunity):*
- If price dropped >2% against position AND no thesis invalidation conditions are met → evaluate as potential add
- Check: is this a stop-hunt pattern? Indicators:
  - Large wick forming (price dropped then recovering within same candle period)
  - Volume spike (>2x avg) with price already bouncing back
  - Price touched a round number or known liquidation cluster then reversed
- If stop-hunt pattern detected AND current position is below max size → add small amount (10% of current position)
- If NOT a stop-hunt (sustained selling, no bounce) → do NOT add, just alert
- Telegram (stop-hunt add): "🎯 Stop-hunt detected: BRENTOIL wicked to $105.20, bounced to $106.80. Added 2 contracts."
- Telegram (sustained dip): "⚠️ BRENTOIL down 2.5% — not a stop-hunt pattern, monitoring."

*Safety constraints on spike/dip actions:*
- Never add if liq distance <12% (need buffer for the add itself)
- Never add if daily drawdown already >3% (don't average into a losing day)
- Never take more than 25% profit in a single spike (preserve core position)
- Max one add per 2 hours (don't get caught adding into a waterfall)
- All actions respect Chris's direction: LONG or NEUTRAL only, never short

**Oil trading hours awareness:**
- Oil market: Sun 6PM ET — Fri 5PM ET
- Outside trading hours: skip stop placement (can't place orders on closed market), suppress "no position" alerts, continue monitoring existing stops and liq distance (exchange still tracks these)

### 1B. BTC Vault Autonomous Trader

The existing `power_law_btc` strategy is a cycle-based rebalancer optimized for SaucerSwap spot. On HL perps it has known weaknesses: IOC failures go unrecovered, no funding cost awareness, no slippage control, no liquidation distance checks, and a 15% deviation threshold that allows excessive drift. The heartbeat wraps around it to fix these gaps.

**What the heartbeat does for BTC (monitor + enhance, minimal changes to strategy code):**

*Trade detection and reporting:*
- Each heartbeat run, compare BTC vault position to last known (from `working_state.json`)
- If position size changed → rebalance happened → log to `action_log`, send Telegram
- Telegram: "₿ BTC Vault rebalance: 0.10→0.11 BTC (bought 0.01 @ $68,420)"

*Execution failure recovery:*
- Track ticks since last successful rebalance vs. current allocation deviation
- If deviation >20% AND no successful rebalance in >3 hours → alert: "₿ BTC rebalance stuck, deviation 23%"
- If deviation >30% AND no rebalance in >6 hours → force rebalance attempt via adapter directly
- Log all recovery attempts to `action_log`

*Funding cost tracking:*
- Track hourly funding rate from HL API
- Compute rolling 30-day annualized funding cost
- If annualized cost >5% → Telegram alert: "₿ BTC funding drag: -X% annualized"
- Store daily funding costs in observations for AI review (Phase 3 optimization target)

*Liquidation distance check (pre-rebalance gate):*
- Before any rebalance that INCREASES position: check liq distance
- If liq distance <15% after proposed increase → block the increase, alert
- This prevents the Power Law strategy from leveraging into danger

*Fee tracking:*
- Track cumulative taker/maker fees from HL account state
- If fees >30% of gross profit → observation logged for AI
- Daily summary → Telegram: "₿ BTC Vault daily: equity $X, PnL +$120, fees: $8, funding: -$3"

*What we DON'T change in Phase 1 (leave for AI autoresearch in Phase 3):*
- Deviation threshold (15%) — could be optimized but not urgent
- IOC vs limit order choice — needs careful backtesting
- Allocation signal parameters — these are the model's core, AI should tune them
- Slippage estimation — needs order book data, more complex

### 1C. Telegram Reporter (pure Python, direct Bot API)

```python
import requests

TELEGRAM_BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
TELEGRAM_CHAT_ID = "5219304680"

def send_telegram(message: str):
    requests.post(
        f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
        json={"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "Markdown"}
    )
```

Messages sent:
- Every trade (entry, exit, partial take, stop hit)
- Every risk action (stop placed, deleverage, position cut)
- Every escalation (L1 alert, L2 action, L3 emergency)
- Every 6 hours: status summary (positions, PnL, conviction, health)
- On significant conviction change (>0.1 shift)

### 1D. Configuration Files

```json
// data/config/profit_rules.json
{
    "xyz:BRENTOIL": {
        "quick_profit_pct": 5.0,
        "quick_profit_window_min": 30,
        "quick_profit_take_pct": 25,
        "extended_profit_pct": 10.0,
        "extended_profit_window_min": 120,
        "extended_profit_take_pct": 25
    },
    "BTC-PERP": {
        "quick_profit_pct": 8.0,
        "quick_profit_window_min": 60,
        "quick_profit_take_pct": 20,
        "extended_profit_pct": 15.0,
        "extended_profit_window_min": 240,
        "extended_profit_take_pct": 25
    }
}
```

```json
// data/config/escalation_config.json
{
    "liq_distance": {
        "L1_alert_pct": 10,
        "L2_deleverage_pct": 8,
        "L2_deleverage_amount": 1,
        "L3_emergency_pct": 5,
        "L3_target_leverage": 3,
        "L2_cooldown_min": 30,
        "L3_cooldown_min": 60
    },
    "drawdown": {
        "L1_alert_pct": 5,
        "L2_cut_pct": 8,
        "L2_cut_size_pct": 25,
        "L3_cut_pct": 12,
        "L3_cut_size_pct": 50
    }
}
```

### 1E. Scheduling (launchd)

One process. Simple.

| Process | Interval | What it does |
|---------|----------|-------------|
| `run_heartbeat.py` | 2 min (StartInterval 120) | Position audit + BTC vault check + escalation + Telegram |

Single entry point. Single PID file. Single log file. Reads config, checks positions, takes action, reports, exits.

**PID enforcement (per `feedback_single_instance.md`):**
1. PID file at `data/memory/pids/heartbeat.pid`
2. On startup: read PID file → `os.kill(pid, 0)` to check alive
3. If alive → exit immediately (previous run still going)
4. If dead or no file → write own PID, proceed
5. On exit (including exceptions) → delete PID file via `atexit` + `try/finally`

**Path resolution:**
All file paths resolved via `PROJECT_ROOT = pathlib.Path(__file__).resolve().parent.parent` (from `scripts/` → `agent-cli/`). Never use `os.getcwd()`.

**Working state atomic writes:**
Write to `working_state.json.tmp`, then `os.rename()` to `working_state.json`. This is atomic on POSIX — the file is always either the old version or the new version, never partial.

### 1F. Edge Cases

| Scenario | Behavior |
|----------|----------|
| No positions open | Skip audit, log "no positions" |
| API down | Retry 3x, log warning, skip cycle, alert after 3 consecutive failures |
| Stop already exists on exchange | Skip — don't double-stop |
| Price gapped through stop level | Stop already triggered on exchange, auditor detects position closed, reports |
| Profit-take would leave <1 contract | Don't take — minimum position size |
| Multiple escalation triggers same cycle | Highest level wins |
| Position opened between cycles | Caught on next 2-min cycle — max 2 min unprotected |
| Spike detected but position is tiny | Skip profit-take if <2 contracts (not worth the fee) |
| Stop-hunt detected but already at max size | Skip add, just alert |
| BTC rebalance stuck >6h | Force rebalance attempt, alert on success/failure |
| BTC liq distance too low for rebalance | Block increase, allow decrease, alert |
| Telegram API down | Log locally, retry next cycle — non-critical |
| Config file missing | Use hardcoded defaults (conservative) |
| Weekend / off-hours | Oil: skip stop placement when market closed, continue liq monitoring. BTC: 24/7 |
| Leverage already at floor (1x) | L2/L3 deleverage skips, alerts only — can't go below 1x |
| Chris manually closes position | Auditor sees no position, does nothing, logs "position closed" |
| Chris manually sets a stop | Auditor sees stop exists, skips, respects Chris's level |

---

## Phase 2: The Memory (records everything)

Builds institutional knowledge. No AI needed to run.

### 2A. Database Schema

Extends existing `data/memory/memory.db` with new tables via `CREATE TABLE IF NOT EXISTS` in existing `_init()`.

**observations** — compressed facts with temporal validity

```sql
CREATE TABLE observations (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at      INTEGER NOT NULL,
    valid_from      INTEGER NOT NULL,
    valid_until     INTEGER,
    superseded_by   INTEGER,
    market          TEXT NOT NULL,
    category        TEXT NOT NULL,     -- position, metric, event, pattern, regime, trade, error
    priority        INTEGER NOT NULL DEFAULT 2,
    title           TEXT NOT NULL,
    body            TEXT,
    tags            TEXT DEFAULT '[]',
    source          TEXT NOT NULL DEFAULT 'programmatic'
);
```

**action_log** — every action with reasoning and outcome

```sql
CREATE TABLE action_log (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp_ms    INTEGER NOT NULL,
    market          TEXT NOT NULL,
    action_type     TEXT NOT NULL,
    detail          TEXT,
    reasoning       TEXT,
    source          TEXT NOT NULL DEFAULT 'programmatic',
    outcome         TEXT
);
```

**execution_traces** — raw logs for Meta-Harness pattern (AI reads these to find bugs)

```sql
CREATE TABLE execution_traces (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp_ms    INTEGER NOT NULL,
    process         TEXT NOT NULL,     -- "heartbeat", "reflector", "btc_rebalancer"
    duration_ms     INTEGER,
    success         INTEGER NOT NULL,  -- 1 or 0
    stdout          TEXT,              -- full stdout capture
    stderr          TEXT,              -- full stderr capture
    actions_taken   TEXT,              -- JSON array of what was done
    errors          TEXT               -- JSON array of errors encountered
);
```

### 2B. What Gets Recorded

The heartbeat (Phase 1) writes to memory every run:

- **execution_traces**: full run log (what was checked, what was found, what was done, any errors)
- **action_log**: every trade, stop placement, profit-take, deleverage, alert sent
- **observations**: significant state changes (position change, regime shift, escalation)

### 2C. Reflector (Phase 2 — built after heartbeat is stable)

Separate launchd process, runs every 30 minutes. Pure Python, no AI.

- Compacts old observations (5+ metrics in 6h → one range summary)
- Backfills outcomes on action_log entries >24h old
- Expires stale observations (priority 3 >7 days, priority 2 >30 days)
- Detects patterns across action_log (repeated errors, escalation frequency)

Spec for reflector will be detailed when Phase 2 is built. For Phase 1, the heartbeat writes to memory tables but no reflector runs.

### 2D. Working State File

`data/memory/working_state.json` — written atomically every heartbeat (tmp + rename):

```json
{
    "last_updated_ms": 1711800000000,
    "session_peak_equity": 775000,
    "session_peak_reset_date": "2026-03-31",
    "positions": {
        "xyz:BRENTOIL": {"size": 20, "side": "long", "entry": 107.65, "mark": 108.10, "upnl": 8500, "leverage": 10, "liq_price": 99.36, "liq_distance_pct": 7.7},
        "BTC-PERP": {"size": 0.11, "side": "long", "entry": 68200, "mark": 68420, "upnl": 24.20, "leverage": 1}
    },
    "escalation": {"current_level": "L0", "last_l2_ms": null, "last_l3_ms": null},
    "last_ai_checkin_ms": null,
    "heartbeat_consecutive_failures": 0,
    "atr_cache": {
        "xyz:BRENTOIL": {"value": 1.85, "cached_at_ms": 1711796000000},
        "BTC-PERP": {"value": 1420, "cached_at_ms": 1711796000000}
    }
}
```

---

## Phase 3: The AI Oversight Loop (enhances everything)

Runs when available. Nothing breaks when it's off.

### 3A. AI Reads Memory (Meta-Harness Pattern)

When OpenClaw runs (scheduled or manual), it:

1. Reads `memory_context()` — compressed observations, action log, patterns
2. Reads recent `execution_traces` — raw logs of heartbeat runs
3. Identifies: bugs, edge cases, inefficiencies, missed opportunities
4. Proposes: code fixes (as observations or direct edits), parameter changes, new research directions
5. Records: what it found and what it changed

**Key insight from Meta-Harness:** Raw execution traces > summaries. The AI can form causal hypotheses about WHY something failed when it sees the actual stdout/stderr.

### 3B. AI Runs Autoresearch (Karpathy Pattern)

Existing `autoresearch_program.md` pattern applies to:

- **BTC Power Law params**: entry/exit thresholds, rebalance frequency, fee optimization
- **Stop placement params**: ATR multiplier, buffer sizes
- **Profit-taking params**: thresholds, windows, take percentages

The ratchet: only keep improvements. Quality gates prevent overfitting.

### 3C. AI Watches Your Back (Thesis Guardian)

For oil:
- Monitors news/events that might invalidate the thesis
- Alerts Chris on Telegram if something major changes
- "⚠️ Reuters reporting Iran ceasefire talks. Your long oil thesis may need review."
- Never trades against Chris's direction — only alerts

For BTC:
- Tracks Power Law model vs actual price
- Flags when model is significantly wrong
- Adjusts parameters via autoresearch loop

### 3D. AI Identifies Dead Code and Focus Areas

Over time, as execution traces accumulate:
- Which code paths actually execute? (track in traces)
- Which code paths never execute? (candidates for archiving)
- Which code paths error frequently? (priority fixes)
- Which strategies contribute most to PnL? (weight accordingly)

---

## File Layout

```
agent-cli/
├── common/
│   ├── memory.py              # EXISTING — add new tables
│   ├── heartbeat.py           # NEW — position auditor + escalation
│   ├── memory_telegram.py     # NEW — direct Telegram Bot API
│   └── memory_context.py      # NEW — context builder for AI (Phase 2/3, not Phase 1)
├── cli/commands/
│   └── memory.py              # NEW — hl memory CLI
├── cli/mcp_server.py          # EXISTING — add memory_* tools
├── data/
│   ├── config/
│   │   ├── profit_rules.json  # NEW
│   │   ├── escalation_config.json # NEW
│   │   └── market_config.json # NEW — canonical ID → API mapping
│   ├── memory/
│   │   ├── memory.db          # EXISTING — extended
│   │   ├── working_state.json # NEW
│   │   ├── pids/              # NEW
│   │   └── logs/              # NEW
├── scripts/
│   └── run_heartbeat.py       # NEW — single launchd entry point
└── plists/
    └── com.hyperliquid.heartbeat.plist  # NEW — one plist, 5-min interval
```

## What We Build First

**Phase 1 only. Get it running. Prove it works.**

1. `heartbeat.py` — position auditor (stops, profit-taking, escalation)
2. `memory_telegram.py` — direct Telegram reporting
3. `run_heartbeat.py` — launchd entry point with PID enforcement
4. `com.hyperliquid.heartbeat.plist` — macOS scheduling
5. Config files with sensible defaults
6. Tests for every edge case listed above

Phase 2 (memory) and Phase 3 (AI) come after Phase 1 is running reliably.
