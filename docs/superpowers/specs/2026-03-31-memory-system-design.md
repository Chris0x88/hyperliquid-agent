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
| **xyz:BRENTOIL** | Manual + Middle Office | Chris picks trades | Protect positions: stops, profit-taking, liq monitoring, alerts |
| **BTC-PERP** (Vault) | Fully Autonomous | Power Law strategy | Trade, manage risk, record, optimize — full stack testbed |

**All trades and risk actions reported to Telegram (chat_id: 5219304680).**

---

## Phase 1: The Heartbeat (protects money today)

Pure Python. launchd. No AI dependency. No human dependency.

### 1A. Position Auditor (runs every 5 minutes)

Reads all open positions from HyperLiquid API. For each position:

**Stop-loss enforcement:**
- If position has NO stop-loss set on exchange → add one
- Stop placement: 3x ATR below entry for longs, above for shorts
- Never place stop within 2% of current price (avoid getting swept on noise)
- Never place stop tighter than liquidation price + 3% buffer
- Telegram: "🛡️ Added stop on BRENTOIL: 20 contracts long, stop @ $103.50 (3x ATR)"

**Profit-taking:**
- If position is up >5% in <30 minutes → take 25% off
- If position is up >10% in <2 hours → take another 25% off
- Configurable per-market in `data/config/profit_rules.json`
- Telegram: "💰 Took 25% profit on BRENTOIL: 5 contracts @ $113.20 (+5.2% in 22min)"

**Liquidation distance monitor:**
- <10% → Telegram alert (L1)
- <8% → reduce leverage by 1x (L2), Telegram alert
- <5% → reduce leverage to 3x (L3), Telegram urgent alert
- Cool-down: L2 max once per 30min, L3 max once per 1h

**Drawdown monitor:**
- >5% from session peak → Telegram alert
- >8% → reduce position 25%, alert
- >12% → reduce position 50%, urgent alert

**Funding rate monitor:**
- If hourly funding >0.1% for 3 consecutive periods → alert with daily drag cost
- If cumulative funding drag >1% of position → alert

### 1B. BTC Vault Autonomous Trader

The existing `power_law_btc` strategy runs via daemon, enhanced with:

**Fee-aware execution:**
- Track cumulative fees paid vs. position gains
- If fees are eating >30% of gross profit → observation logged, AI can investigate
- Prefer limit orders over market orders where possible (maker vs taker fees)

**Funding-cost-aware holding:**
- Track daily funding costs as % of position
- If holding cost >X% annualized → log observation for AI review
- Power Law rebalancer already handles entry/exit — just needs cost tracking

**Trade reporting:**
- Every rebalance action → Telegram: "₿ BTC Vault rebalance: bought 0.01 BTC @ $68,420 (Power Law signal: undervalued)"
- Daily summary → Telegram: "₿ BTC Vault daily: +$120 (+0.03%), fees: $8, funding: -$3"

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
| `run_heartbeat.py` | 5 min | Position audit + BTC vault check + escalation + Telegram |

Single entry point. Single PID file. Single log file. Reads config, checks positions, takes action, reports, exits.

### 1F. Edge Cases

| Scenario | Behavior |
|----------|----------|
| No positions open | Skip audit, log "no positions" |
| API down | Retry 3x, log warning, skip cycle, alert after 3 consecutive failures |
| Stop already exists on exchange | Skip — don't double-stop |
| Price gapped through stop level | Stop already triggered on exchange, auditor detects position closed, reports |
| Profit-take would leave <1 contract | Don't take — minimum position size |
| Multiple escalation triggers same cycle | Highest level wins |
| Position opened between cycles | Caught on next 5-min cycle — max 5 min unprotected |
| Telegram API down | Log locally, retry next cycle — non-critical |
| Config file missing | Use hardcoded defaults (conservative) |
| Weekend / off-hours | Same behavior — oil has specific hours, BTC is 24/7 |
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

The reflector (30-min cron) compacts observations and backfills outcomes.

### 2C. Working State File

`data/memory/working_state.json` — written atomically every heartbeat:

```json
{
    "last_updated_ms": 1711800000000,
    "positions": { ... },
    "escalation": { "current_level": "L0" },
    "last_ai_checkin_ms": null,
    "heartbeat_consecutive_failures": 0
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
│   └── memory_context.py      # NEW — context builder for AI
├── cli/commands/
│   └── memory.py              # NEW — hl memory CLI
├── cli/mcp_server.py          # EXISTING — add memory_* tools
├── data/
│   ├── config/
│   │   ├── profit_rules.json  # NEW
│   │   └── escalation_config.json # NEW
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
