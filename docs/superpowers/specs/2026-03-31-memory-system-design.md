# Programmatic Memory Engine — Design Specification

**Date:** 2026-03-31
**Status:** Draft
**Author:** Claude (brainstorming session with Chris)

## Problem

The 5-minute scheduled trading check-in system failed because each OpenClaw session started with zero memory of prior sessions. This caused repeated mistakes, contradictory trades, and required constant human intervention.

## Solution

A programmatic memory engine that maintains continuous trading context across sessions. Python handles 90% of the work (structured data compression, temporal tracking, pattern detection). OpenClaw consumes pre-compressed memory and handles only high-level synthesis.

Inspired by Mastra's Observational Memory architecture (94.87% on LongMemEval) but implemented entirely in Python with no LLM dependency for core memory operations. For structured trading data with proper temporal indexing, programmatic memory achieves effectively 100% factual recall accuracy.

## Architecture Overview

```
HyperLiquid API ──┐
ThesisState JSON ──┤
SQLite events ─────┤──→ [Observer] ──→ observations table ──→ [Reflector] ──→ compacted observations
Research files ────┘        │                                      │
                            ▼                                      ▼
                    working_state.json                   belief drift detection
                            │                            pattern detection
                            ▼                            outcome backfill
                    [Context Builder] ──→ markdown context block ──→ OpenClaw
                                                                      │
                                                                      ▼
                                                              memory_observe() writes back
                                                              ThesisState updates (existing)
                                                              Telegram reports (existing)
```

Three independent scheduled processes:
- **Observer**: every 5 minutes, reads raw data, writes observations + working_state.json
- **Reflector**: every 30 minutes, compacts, detects drift, backfills outcomes
- **Context Builder**: on-demand, assembles context block for OpenClaw consumption

## 1. Data Model — Temporal Knowledge Base

Extends existing `data/memory/memory.db` (SQLite) with three new tables. Existing `events` and `learnings` tables are untouched.

### 1.1 observations

Compressed facts with temporal validity windows. Append-only with soft invalidation.

```sql
CREATE TABLE observations (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at      INTEGER NOT NULL,           -- ms, when recorded
    valid_from      INTEGER NOT NULL,           -- ms, when fact became true
    valid_until     INTEGER,                    -- ms, NULL = still valid
    superseded_by   INTEGER REFERENCES observations(id),
    market          TEXT NOT NULL,              -- "xyz:BRENTOIL", "BTC-PERP", "PORTFOLIO"
    category        TEXT NOT NULL,              -- "position", "thesis", "event", "pattern", "metric"
    priority        INTEGER NOT NULL DEFAULT 2, -- 1=critical, 2=relevant, 3=contextual
    title           TEXT NOT NULL,              -- one-line summary
    body            TEXT,                       -- full detail
    tags            TEXT DEFAULT '[]',          -- JSON array
    source          TEXT NOT NULL DEFAULT 'programmatic'  -- "programmatic", "openclaw", "user"
);

CREATE INDEX idx_obs_active ON observations(market, category) WHERE valid_until IS NULL;
CREATE INDEX idx_obs_market_time ON observations(market, created_at);
```

### 1.2 belief_states

Conviction snapshots. Every change is a new row — full audit trail, never overwritten.

```sql
CREATE TABLE belief_states (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp_ms            INTEGER NOT NULL,
    market                  TEXT NOT NULL,
    direction               TEXT NOT NULL,      -- "long", "short", "flat"
    conviction              REAL NOT NULL,       -- 0.0-1.0
    thesis_summary          TEXT,
    invalidation            TEXT DEFAULT '[]',   -- JSON array
    evidence_for            TEXT DEFAULT '[]',   -- JSON array
    evidence_against        TEXT DEFAULT '[]',   -- JSON array
    recommended_leverage    REAL DEFAULT 5.0,
    trigger                 TEXT                 -- what caused this update
);

CREATE INDEX idx_belief_market_time ON belief_states(market, timestamp_ms);
```

### 1.3 action_log

Every action the system takes, with reasoning captured at decision time.

```sql
CREATE TABLE action_log (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp_ms    INTEGER NOT NULL,
    market          TEXT NOT NULL,
    action_type     TEXT NOT NULL,              -- "open", "close", "add", "reduce", "alert", "thesis_update"
    detail          TEXT,                       -- JSON, action-specific payload
    reasoning       TEXT,                       -- why this action was taken
    outcome         TEXT                        -- filled later by Reflector
);

CREATE INDEX idx_action_market_time ON action_log(market, timestamp_ms);
```

### 1.4 action_log detail schemas

The `detail` JSON field in `action_log` has a defined schema per `action_type`:

```python
# action_type: "open" / "close" / "add" / "reduce"
{"side": "long", "size": 5, "price": 107.65, "leverage": 10, "prev_size": 20, "new_size": 25}

# action_type: "thesis_update"
{"direction": "long", "prev_conviction": 0.7, "new_conviction": 0.85, "prev_leverage": 8, "new_leverage": 10}

# action_type: "alert"
{"alert_type": "liq_distance", "value": 7.7, "threshold": 10.0}
```

This enables the Reflector to programmatically determine predicted direction and magnitude for outcome backfill.

### 1.5 Market identifier convention

Canonical market identifiers used throughout the memory system:

| Market | Canonical ID | ThesisState file slug | Notes |
|--------|--------------|-----------------------|-------|
| Brent Oil | `xyz:BRENTOIL` | `xyz_brentoil` | xyz perps need `dex='xyz'` |
| Bitcoin | `BTC-PERP` | `btc-perp` | Main vault, Power Law |
| Portfolio-wide | `PORTFOLIO` | N/A | Cross-market observations only |

All memory tables use the canonical ID. The Observer maps from ThesisState file slugs (colons replaced with underscores) to canonical IDs on read.

### 1.6 Schema migration

New tables are added to the existing `_init()` method in `common/memory.py` using `CREATE TABLE IF NOT EXISTS`, matching the existing pattern for `events` and `learnings` tables. No separate migration framework. This is safe because:
- `IF NOT EXISTS` is idempotent — running on an existing DB adds nothing
- New tables have no foreign keys to existing tables
- Existing tables and data are untouched

### Design decisions

- **Append-only with soft invalidation**: observations never deleted, only `valid_until` set and `superseded_by` linked. Full audit trail.
- **Belief states are snapshots**: conviction over time is chartable from this table.
- **Action log captures reasoning at decision time**: not reconstructed after the fact.
- **All timestamps in milliseconds**: matches existing `events` table convention.
- **`market = "PORTFOLIO"`**: for cross-market observations.

## 2. Programmatic Observer

Python module that runs every 5 minutes via launchd. Reads raw data sources, produces compressed observations. No LLM calls.

### Input sources

1. **HyperLiquid API** → current positions, PnL, funding, liquidation distance
2. **ThesisState JSON** (`data/thesis/{market}_state.json`) → current conviction, direction, evidence
3. **SQLite events table** → recent events not yet captured as observations
4. **Research signals** (`data/research/markets/*/signals.jsonl`) → latest signals (written by OpenClaw research skill; gracefully skipped if file missing or empty)

### Observation rules

| Condition | Category | Priority | Example |
|-----------|----------|----------|---------|
| Position size changed | position | 1-critical | "BRENTOIL: 20→25 contracts, entry $107.65" |
| PnL moved >2% since last obs | metric | 2-relevant | "BRENTOIL UPNL: +$8.5K→+$12.1K (+42%)" |
| Conviction changed in ThesisState | thesis | 1-critical | "BRENTOIL conviction: 0.7→0.85" |
| Liquidation distance <10% | metric | 1-critical | "BRENTOIL liq distance: 7.7%" |
| Funding rate anomaly (>0.1% or <-0.05%) | metric | 2-relevant | "BRENTOIL funding: +0.15% (elevated)" |
| New event in SQLite events table | event | 2-relevant | Pass-through with temporal tag |
| No change detected | — | — | No observation created (silence = stability) |

### Deduplication logic

Before writing an observation:
1. Query active observations (valid_until IS NULL) with same market + category
2. Check if data has materially changed using per-category thresholds:
   - **position**: size changed by any amount, OR entry price changed
   - **metric** (PnL): absolute change >1% of account equity
   - **metric** (liq distance): change >0.5 percentage points
   - **metric** (funding): change >0.02%
   - **thesis**: conviction change >=0.05, OR direction change, OR evidence list length changed
   - **event**: always new (events are unique by nature)
   - **pattern**: title differs from existing active pattern observation
3. If below threshold → skip (no observation created)
4. If above threshold → supersede old observation (set valid_until + superseded_by), write new one

### Working Memory State File

Written atomically every Observer run to `data/memory/working_state.json`:

```json
{
    "last_updated_ms": 1711800000000,
    "account": {
        "equity": 770000,
        "available_margin": 450000,
        "daily_pnl": 1200,
        "daily_pnl_pct": 0.16
    },
    "positions": {
        "xyz:BRENTOIL": {
            "size": 20, "side": "long", "entry": 107.65,
            "mark": 108.10, "upnl": 8500, "leverage": 10,
            "liq_price": 99.36, "liq_distance_pct": 7.7,
            "funding_rate": 0.012
        }
    },
    "theses": {
        "xyz:BRENTOIL": {
            "direction": "long", "conviction": 0.8,
            "summary": "10M+ bpd gap unfillable in 2026",
            "stale": false, "age_hours": 2.5
        }
    },
    "active_observations": 12,
    "last_action": "thesis_update at 2026-03-30T14:00:00"
}
```

### Edge cases

- **API timeout**: catch exception, write warning observation "API unreachable", use last working_state.json
- **ThesisState file missing**: conviction defaults to 0.3. Note: in existing `thesis.py`, `is_stale` (>24h) and `is_very_stale` (>6h) have inverted naming. The Observer uses `is_stale` (>24h) as the threshold for the `stale` field in working_state.json and for generating "thesis needs re-evaluation" open questions
- **First run ever**: creates baseline observations for all current state, no "change" observations
- **Multiple markets**: each processed independently, plus PORTFOLIO-level if cross-market metrics warrant

## 3. Programmatic Reflector

Runs every 30 minutes. Garbage collection, pattern detection, belief drift tracking. Pure Python, no LLM.

### Job 1: Observation Compaction

- 5+ `metric` observations for same market within a rolling 6-hour window from current time → compact into one range summary
- Supersede individuals, point to compacted observation
- Priority 1 (critical) observations **never compacted**
- Cap: max ~50 active observations. If over, compact oldest priority 3 first
- Never compact below 5 active observations

### Job 2: Belief Drift Detection

Query `belief_states` for last 7 days per market:
- 3+ consecutive conviction increases → observation: "conviction trending UP"
- 3+ consecutive decreases → observation: "conviction trending DOWN" (priority 1)
- Up/down/up/down pattern → observation: "conviction unstable, N reversals in 7 days"
- No change >3 days → observation: "conviction stable at X for N days"

### Job 3: Staleness Sweep

- Priority 3 older than 7 days → auto-expire (set valid_until)
- Priority 2 older than 30 days → auto-expire
- Priority 1 → never auto-expire, only superseded explicitly
- belief_states and action_log → never expire (permanent audit trail)

### Job 4: Outcome Backfill

Check `action_log` entries where `outcome IS NULL`:
- **Trade actions** (open/close/add/reduce) older than 24h → compute current PnL from position tracker, fill outcome: `"position +4.2% after 24h"` or `"position closed, realized +$1200"`
- **Thesis updates** older than 48h → read `detail.direction` and `detail.new_conviction` from the action's JSON detail field (see section 1.4), compare against price movement since `timestamp_ms`. Outcome: `"thesis confirmed, price +$3.20 in direction"` or `"thesis unconfirmed, price flat"`
- **Alerts** older than 6h → re-check the condition (e.g., liq distance). Outcome: `"resolved, liq distance now 12%"` or `"persisting, liq distance still 8%"`
- **Skip** any action_log entries modified in the last 60 seconds (avoid race with Observer)

### Job 5: Cross-Market Pattern Detection

- BTC + BRENTOIL both up >2% same day → "hedge not working today"
- Inverse move >2% → "natural hedge active"
- Only triggers on significant moves

## 4. OpenClaw Integration — Context Builder

Assembles pre-compressed memory into a prompt-ready markdown block.

### Context block format

```markdown
# Trading Memory Context
Generated: 2026-03-30T14:05:00 AEST

## Working State
[working_state.json rendered as readable summary]

## Active Observations (12)
### Critical (3)
- 🔴 2026-03-30 11:00: BRENTOIL liq distance 7.7% at 10x [active 5h]
- 🔴 2026-03-29 22:00: Hormuz escalation — Iran threatens mining [active 16h]
- 🔴 2026-03-30 09:00: Conviction UP 0.7→0.85 on supply data [active 5h]

### Relevant (6)
- 🟡 [observations listed with timestamps and age]

### Contextual (3)
- 🟢 [observations listed]

## Belief Trajectory
- BRENTOIL: conviction 0.85 ▲ trending up (0.6→0.7→0.8→0.85 over 8 days)
- BTC: conviction 0.6 ▬ stable for 12 days

## Recent Actions (last 24h)
- [timestamp]: [action_type] — [reasoning]

## Patterns Detected
- [Reflector-generated pattern observations]

## Open Questions for Reflection
- [Programmatically generated from data discrepancies]
```

### Open Questions generator

Python detects discrepancies and poses them as questions for OpenClaw:
- Conviction high but position small → "sizing mismatch?"
- Liq distance shrinking over 3 checks → "leverage creep detected"
- Thesis stale >24h → "thesis needs re-evaluation"
- PnL drawdown >5% from peak → "dip or thesis weakening?"
- Funding rate elevated 3 days → "funding drag accumulating"

### Truncation

Context block capped at 8000 chars (OpenClaw prompt budget — not the Telegram limit which is separate). The Telegram report is a distinct downstream output, not the context block itself. Truncation order: contextual first, then relevant, never critical.

### Changed OpenClaw flow

Old: `scheduled_check.py` → raw data → OpenClaw processes from scratch → loses everything

New:
1. `memory_health()` → confirm GREEN
2. `memory_context()` → pre-compressed context with full history
3. OpenClaw reasons about open questions
4. `memory_observe()` → log new observations. OpenClaw writes observations with `source: "openclaw"` and typically uses:
   - `category: "event"` for new geopolitical/market events discovered during web search
   - `category: "thesis"` for thesis re-evaluations with updated reasoning
   - `category: "pattern"` for cross-referencing patterns the programmatic system can't detect
   - `priority: 1` for thesis-altering insights, `priority: 2` for supplementary context
5. ThesisState update (existing flow)
6. Telegram report (existing flow)

## 5. Scheduling, Single-Instance Enforcement, and Failure Recovery

### Three independent processes

| Process | Interval | Runtime | Entry point |
|---------|----------|---------|-------------|
| Observer | 5 min | <2 sec | `scripts/run_observer.py` |
| Reflector | 30 min | <5 sec | `scripts/run_reflector.py` |
| Context Builder | On-demand | <1 sec | `memory_context()` MCP tool |

### Single-instance enforcement (PID pattern)

PID files in `data/memory/pids/observer.pid` and `data/memory/pids/reflector.pid`.

On startup:
1. Check PID file exists
2. If yes, check process alive (`os.kill(pid, 0)`)
3. If alive → exit silently (don't stack)
4. If dead → stale PID, delete, proceed
5. Write own PID → work → delete PID on exit

### launchd plists

Two plists in `~/Library/LaunchAgents/`:
- `com.hyperliquid.observer.plist` — StartInterval 300 (5 min)
- `com.hyperliquid.reflector.plist` — StartInterval 1800 (30 min)

Both use:
- WorkingDirectory: `/Users/cdi/Developer/HyperLiquid_Bot/agent-cli` (absolute path, never relative)
- StandardOutPath/StandardErrorPath: absolute paths to `data/memory/logs/`
- KeepAlive: false (run and exit)
- EnvironmentVariables: PYTHONPATH=`.`, PATH includes `/opt/homebrew/bin` (Python 3.13)

**Critical: all file paths in the codebase use `pathlib.Path(__file__).parent` relative resolution, NOT `os.getcwd()`.** This prevents the silent "second database" bug where launchd's WorkingDirectory doesn't match expectations. The `common/memory.py` `_DB_PATH` is resolved relative to the project root via `__file__`, not the process CWD.

### Failure recovery

| Failure | Behavior | Recovery |
|---------|----------|---------|
| HL API down | Warning observation, use last state | Next run retries |
| SQLite locked | Retry 3x, 100ms backoff | Skip run if still locked. WAL mode enabled on DB open for concurrent read support |
| Observer/Reflector write race | Reflector skips observations with `created_at` within last 60 seconds | Prevents superseding an observation the Observer is about to update |
| working_state.json corrupt | Atomic write (tmp + rename) | Always valid |
| Observer crash mid-run | Stale PID file | Next run detects, cleans up |
| Mac sleep | launchd queues, fires on wake | PID prevents stacking |
| Disk full | OSError caught, logged to stderr | Existing data untouched |
| Python not found | launchd logs error | PATH in plist env |
| First run (empty DB) | Baseline observations created | Same code path |

### Log rotation

Observer/Reflector logs capped at 1MB. On startup, if >1MB, rename to `.log.old` (one backup).

### Health check

`hl memory health` / `memory_health()` MCP tool:
- GREEN: all systems normal
- YELLOW: observations stale >10min, or working_state >15min old
- RED: SQLite unreadable, working_state missing/unparseable

## 6. CLI Interface and MCP Tools

### CLI commands (`hl memory`)

```bash
# Read
hl memory status                     # Working state summary
hl memory observations               # Active observations by priority
hl memory observations --market M    # Filter by market
hl memory beliefs                    # Belief trajectory all markets
hl memory beliefs --market M --days N # Conviction history
hl memory actions --days N           # Recent action log
hl memory context                    # Full context block
hl memory health                     # System health

# Write
hl memory observe "title" --market M --priority N --body "detail"
hl memory learn "title" --lesson "..." --topic T --market M

# Maintenance
hl memory gc                         # Force reflector run
hl memory reset                      # Drop observations (confirmation required)
hl memory export --days N            # Dump as JSON
```

### MCP tools (added to mcp_server.py)

Following existing tool patterns (docstring with `Args:` section, return type annotation):

```python
def memory_status() -> str:
    """Get current working memory state (positions, equity, theses).
    Returns: JSON string of working_state.json contents."""

def memory_context() -> str:
    """Get full pre-compressed trading memory context block.
    Returns: Markdown-formatted context with observations, beliefs, patterns, open questions."""

def memory_observe(title: str, market: str, priority: int = 2, body: str = "", category: str = "event") -> str:
    """Write a new observation to the memory system.
    Args:
        title: One-line summary of the observation.
        market: Canonical market ID (xyz:BRENTOIL, BTC-PERP, PORTFOLIO).
        priority: 1=critical, 2=relevant, 3=contextual. Default 2.
        body: Full detail text. Optional.
        category: One of: position, thesis, event, pattern, metric. Default event.
    Returns: Confirmation with observation ID."""

def memory_learn(title: str, lesson: str, topic: str, market: str = "") -> str:
    """Log a learning to the memory system (delegates to existing learnings table).
    Args:
        title: Short title for the learning.
        lesson: What was learned.
        topic: Topic tag (oil, btc, risk, execution, etc.).
        market: Optional canonical market ID.
    Returns: Confirmation with learning ID."""

def memory_health() -> str:
    """Check memory system health.
    Returns: GREEN, YELLOW, or RED with reason."""

def memory_beliefs(market: str = "", days: int = 7) -> str:
    """Get belief/conviction trajectory for a market.
    Args:
        market: Canonical market ID. Empty string for all markets.
        days: Lookback period. Default 7.
    Returns: JSON array of belief_state snapshots."""

def memory_actions(days: int = 1) -> str:
    """Get recent action log with reasoning and outcomes.
    Args:
        days: Lookback period. Default 1.
    Returns: JSON array of action_log entries."""
```

### File layout

```
agent-cli/
├── common/
│   ├── memory.py              # EXISTING — add new tables, keep existing API
│   ├── memory_observer.py     # NEW
│   ├── memory_reflector.py    # NEW
│   ├── memory_context.py      # NEW
│   └── memory_health.py       # NEW
├── cli/commands/
│   └── memory.py              # NEW (follows convention: daemon.py, journal.py, etc.)
├── cli/mcp_server.py          # EXISTING — add memory_* tools
├── cli/main.py                # EXISTING — add: app.add_typer(memory_app, name="memory")
├── data/memory/
│   ├── memory.db              # EXISTING — extended
│   ├── working_state.json     # NEW
│   ├── pids/                  # NEW
│   └── logs/                  # NEW
├── scripts/
│   ├── run_observer.py        # NEW
│   └── run_reflector.py       # NEW
└── plists/
    ├── com.hyperliquid.observer.plist   # NEW
    └── com.hyperliquid.reflector.plist  # NEW
```

## 7. Testing and Validation

### Unit tests

**memory_observer.py:**
- Deduplication: same data twice → one observation
- Priority assignment: liq distance 8% → critical, 15% → relevant
- API failure: warning observation, no crash
- First run: baseline observations from empty DB
- Supersession: new observation expires old correctly

**memory_reflector.py:**
- Compaction: 6 metrics → 1 range summary
- Never compact below 5 active observations
- Never compact priority 1
- Belief drift: 3 consecutive increases → "trending UP"
- Staleness: 8-day priority 3 → expired
- Outcome backfill: 24h trade gets PnL

**memory_context.py:**
- Output under 8000 chars with 50 observations
- Truncation order: contextual → relevant → never critical
- Empty DB → valid context with "no observations yet"
- Open questions from data discrepancies

**memory_health.py:**
- GREEN when normal
- YELLOW when stale >10min
- RED when SQLite unreadable

**Schema migration:**
- Existing memory.db gets new tables without losing events/learnings

### Edge case tests

```
test_empty_position()               # No positions → no crash
test_negative_pnl()                 # Large loss → observation created
test_midnight_rollover()            # Date boundary → correct timestamps
test_thesis_file_deleted()          # Missing → conviction 0.3, warning
test_unicode_in_observation()       # Non-ASCII → stored correctly
test_db_locked_during_write()       # Concurrent → retry works
test_very_long_observation()        # 10K body → stored, truncated in context
test_clock_skew()                   # Clock jump → monotonic timestamps
test_disk_full()                    # OSError → caught, existing data safe
test_nan_pnl()                      # NaN/None → handled, not written
test_zero_equity()                  # Drained → critical obs, no div-by-zero
test_rapid_conviction_changes()     # 10 updates/min → all captured, deduped
```

### Validation before deployment

1. Run full test suite
2. Dry-run Observer against live API (read-only, print what it would write)
3. Dry-run Reflector against seeded test DB
4. Generate context block, visually inspect
5. Load launchd plists, verify firing
6. `hl memory health` → GREEN

## Future: Algorithm Trading Extension

The memory system naturally extends to algorithmic trading without schema changes:
- Algorithm trades log to `action_log` with `source: "algorithm"`
- Algorithm metrics land in `observations` with `category: "pattern"`
- Algorithm confidence → `belief_states` (conviction = confidence score)
- Reflector outcome backfill tracks algorithm profitability automatically
- Future additions: `category: "parameter_change"` for AI-tuned algorithm params, cross-strategy disagreement detection
