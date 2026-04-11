# Learning Path: Data Storage & Flow

Where all data lives, who writes it, who reads it, and how it grows. Read these files in order.

---

## 1. `data/` -- Directory structure overview

**Start here.** Scan the top-level data directory to see the full landscape:

```
data/
├── agent_memory/       # AI agent conversation memory + dream consolidation
├── calendar/           # Economic calendar events (iCal format)
├── candles/            # Market OHLCV data (SQLite)
├── config/             # Runtime configuration (25 files, see understanding-config.md)
├── daemon/             # Daemon runtime state, logs, PID files, chat history
├── feedback.jsonl      # User feedback entries
├── guard/              # Dynamic stop-loss guard state
├── heatmap/            # Liquidity zones + cascade events (sub-system 3)
├── memory/             # Lessons, events, observations (SQLite + backups)
├── news/               # Catalysts + headlines (sub-system 1)
├── research/           # Trade journal, bot patterns, evaluations, learnings
├── snapshots/          # Account equity snapshots (time series)
├── strategy/           # Oil bot pattern state, journals, shadow positions
├── supply/             # Physical oil disruption state (sub-system 2)
└── thesis/             # Per-market conviction files (AI-written JSON)
```

**What you'll learn:** The overall data topology and which subsystem owns which directory.

---

## 2. `data/candles/candles.db` -- Market data (SQLite, WAL mode)

**The price backbone.** A single SQLite database storing OHLCV candles for all watched markets across multiple intervals.

- **Writer:** `modules/candle_cache.py` -- polls HyperLiquid API, inserts candles, deduplicates by (coin, interval, timestamp)
- **Readers:** `market_structure_iter.py` (ATR/technicals), `charts.py` web router, `analyze_market` agent tool
- **Format:** SQLite with WAL (Write-Ahead Logging) for concurrent read/write
- **Growth:** ~1.5 MB base + ~100 KB/day depending on watchlist size and intervals
- **Intervals:** 1m, 5m, 15m, 1h, 4h, 1d (defined in `modules/candle_cache.py :: INTERVAL_MS`)
- **Retention:** No automatic pruning -- grows indefinitely. The web charts router backfills from HL API if cached candles are below 50 for a given coin/interval.

**What you'll learn:** How candle data flows from exchange API to SQLite to all consumers.

---

## 3. `data/thesis/*.json` -- Conviction files (AI-written)

**The bridge between AI judgment and mechanical execution.** One JSON file per market, named by slug:

```
data/thesis/
├── btc_perp_state.json
├── challenges.jsonl           # thesis challenge history
├── xyz_brentoil_state.json
├── xyz_cl_state.json
├── xyz_gold_state.json
├── xyz_silver_state.json
└── xyz_sp500_state.json
```

- **Writer:** AI agent via `update_thesis` tool (requires user approval), `thesis_updater` iterator (Haiku-powered auto-updates)
- **Readers:** `thesis_engine.py` iterator (loads into `ctx.thesis_states`), `execution_engine.py` (conviction -> sizing), `exchange_protection.py` (TP from `take_profit_price`)
- **Format:** JSON matching `common/thesis.py :: ThesisState` dataclass
- **Lifecycle:** Overwritten on each update. Staleness taper kicks in after 24h (needs_review), 7d (linear taper), 14d (clamp to 0.3)
- **Growth:** Constant size per market (~2-5 KB each). Not append-only.

See [thesis-to-order.md](thesis-to-order.md) for the full pipeline from thesis to executed order.

**What you'll learn:** How conviction data is structured, who writes vs reads it, and the staleness model.

---

## 4. `data/research/journal.jsonl` -- Trade history (append-only)

**The source of truth for closed trades.** Each line is a JSON object representing one completed trade.

- **Writer:** `execution_engine.py` (appends on position close), `oil_botpattern.py` (appends closed bot-pattern trades)
- **Readers:** `lesson_author.py` (detects new closed trades for post-mortem), `trade_journal` agent tool, web dashboard strategies router
- **Format:** JSONL -- one JSON object per line, append-only
- **Key fields:** market, direction, entry_price, exit_price, pnl, duration, thesis_at_entry, exit_reason
- **Growth:** ~0.5-2 KB per trade. Low volume (thesis-driven trading = few trades per week).

Related research files:
- `research/bot_patterns.jsonl` -- sub-system 4 output, ~200 KB and growing. Classification of recent moves as bot/informed/mixed.
- `research/entry_critiques.jsonl` -- entry critic grading of new positions
- `research/learnings.md` -- rolling markdown file of agent learnings (trimmed by `memory_consolidator.py`)
- `research/evaluations/` -- directory of per-cycle evaluation files from auto-research

**What you'll learn:** The trade journal schema and the constellation of research artifacts that support post-trade learning.

---

## 5. `data/memory/memory.db` -- Lessons, events, observations (SQLite, FTS5)

**The agent's long-term memory.** Canonical owner: `common/memory.py`.

Tables (migrated by `_init()` in `common/memory.py`):
| Table | Purpose | Key columns |
|-------|---------|-------------|
| `events` | Timestamped event log | ts, event_type, payload |
| `learnings` | Agent-discovered insights | ts, market, insight, confidence |
| `observations` | Market observations | ts, market, observation |
| `action_log` | Actions taken by agent | ts, action, result |
| `execution_traces` | Detailed execution traces | ts, trace_data |
| `account_snapshots` | Periodic equity snapshots | ts, equity, positions |
| `summaries` | Compressed conversation summaries | ts, summary |
| `lessons` | Trade post-mortem lessons | market, direction, lesson_type, summary, body_full, tags |
| `lessons_fts` | FTS5 virtual table over lessons | BM25 search over summary + body_full + tags |

- **Writers:** `common/memory.py` helpers (`log_event`, `log_learning`, `log_lesson`, etc.), `lesson_author` iterator (writes lesson candidates that become full lessons)
- **Readers:** `build_lessons_section()` in `agent_runtime.py` (FTS5 search for prompt injection), `search_lessons` tool, web dashboard
- **Growth:** ~2 MB base. Events and observations grow steadily; lessons grow with closed trades.
- **Backup:** `memory_backup` iterator takes hourly atomic snapshots to `data/memory/backups/` with 24h/7d/4w retention tiers.

**What you'll learn:** The memory schema, FTS5 search, and how lessons connect the trade journal to the agent's prompt.

---

## 6. `data/news/` + `data/heatmap/` + `data/supply/` -- Intelligence pipeline

**The oil bot pattern's three input streams.** Each sub-system writes to its own directory:

### `data/news/` (Sub-system 1: News Ingestion)
- `catalysts.jsonl` -- structured catalyst events from RSS/iCal feeds (~15 KB)
- `headlines.jsonl` -- raw headline archive (~74 KB)
- **Writer:** `news_ingest` iterator
- **Readers:** `bot_classifier`, `thesis_challenger`, `thesis_updater`, web news router
- **Growth:** Append-only, ~1-5 KB/day depending on news volume

### `data/heatmap/` (Sub-system 3: Liquidity Heatmap)
- `zones.jsonl` -- clustered liquidity zones from L2 orderbook polling (~874 KB)
- `cascades.jsonl` -- liquidation cascade events from OI/funding deltas (when generated)
- **Writer:** `heatmap` iterator (polls HL `l2Book` + `metaAndAssetCtxs`)
- **Readers:** `bot_classifier`, `oil_botpattern` strategy engine
- **Growth:** `zones.jsonl` grows fastest (~50 KB/day), may need periodic trimming

### `data/supply/` (Sub-system 2: Supply Ledger)
- `state.json` -- aggregated active physical oil disruptions (~265 bytes, overwritten)
- `disruptions.jsonl` -- individual disruption events (~13 KB, append-only)
- **Writer:** `supply_ledger` iterator
- **Readers:** `oil_botpattern` strategy engine, `bot_classifier`
- **Growth:** Minimal. Disruptions resolve; state.json is always small.

**What you'll learn:** How the three intelligence sub-systems feed data to the bot classifier and strategy engine.

---

## 7. `data/strategy/` -- Oil bot pattern state

**Runtime state for the strategy engine.** All files written by `oil_botpattern.py` (sub-system 5) and its tuning layers:

| File | Type | Purpose |
|------|------|---------|
| `oil_botpattern_state.json` | Overwritten | Current strategy state (enabled_since, last decisions, drawdown counters) |
| `oil_botpattern_journal.jsonl` | Append-only | Per-decision journal (every sizing/entry/exit decision with reasoning) |
| `oil_botpattern_adaptive_log.jsonl` | Append-only | Adaptive evaluator output (~2.5 MB, the fastest-growing file) |
| `oil_botpattern_shadow_positions.json` | Overwritten | Current shadow (paper) positions |
| `oil_botpattern_shadow_balance.json` | Overwritten | Shadow portfolio balance |
| `oil_botpattern_shadow_trades.jsonl` | Append-only | Shadow trade history |
| `oil_botpattern_activation_log.jsonl` | Append-only | Kill switch activation/deactivation log |

**Growth concern:** `oil_botpattern_adaptive_log.jsonl` at 2.5 MB is the largest strategy file. It logs every adaptive evaluation (every 15 minutes). Consider periodic archival if it exceeds 10 MB.

**What you'll learn:** The state/journal split pattern, and which files are append-only vs overwritten.

---

## Data flow diagram

```
                    EXTERNAL
                       |
        ┌──────────────┼──────────────┐
        v              v              v
   HyperLiquid     RSS/iCal       User input
   Exchange API     feeds          (Telegram)
        |              |              |
        v              v              v
   ┌─────────┐   ┌──────────┐   ┌──────────┐
   │ candles/ │   │  news/   │   │ thesis/  │
   │ .db      │   │ .jsonl   │   │ .json    │
   └────┬─────┘   └────┬─────┘   └────┬─────┘
        |              |              |
   ┌────┴──────────────┴──────────────┴────┐
   │            Daemon iterators            │
   │  (connector, thesis_engine, heatmap,   │
   │   bot_classifier, oil_botpattern, ...) │
   └────┬──────────────┬──────────���───┬────┘
        |              |              |
        v              v              v
   ┌─────────┐   ┌──────────┐   ┌──────────┐
   │strategy/│   │ research/│   │ memory/  │
   │ state   │   │ journal  │   │ .db      │
   │ journal │   │ patterns │   │ lessons  │
   └─────────┘   └──────────┘   └──────────┘
        |              |              |
        └────────���─────┴──────────────┘
                       |
                       v
              ┌──────────────┐
              │   Web API    │
              │  (readers/)  │
              └──────┬───────┘
                     |
                     v
               Dashboard UI
```

### Append-only vs overwritten

| Pattern | Files | Notes |
|---------|-------|-------|
| **Append-only (JSONL)** | `journal.jsonl`, `bot_patterns.jsonl`, `catalysts.jsonl`, `headlines.jsonl`, `zones.jsonl`, all `*_journal.jsonl` | Grows indefinitely. Needs periodic archival for large files. |
| **Overwritten** | `oil_botpattern_state.json`, `supply/state.json`, `shadow_positions.json`, `shadow_balance.json`, all `data/config/*.json` | Constant size. Atomic writes via tmp+rename pattern. |
| **SQLite** | `candles.db`, `memory.db` | WAL mode for concurrent access. `memory.db` has hourly backups. |

### Backup strategy

Only `data/memory/memory.db` has automated backups via the `memory_backup` iterator:
- Hourly atomic snapshots to `data/memory/backups/`
- Retention: last 24 hourly + last 7 daily + last 4 weekly
- Restore runbook: `docs/wiki/operations/memory-restore-drill.md`

Everything else relies on git (config files are tracked) or is regenerable from the exchange API (candles, positions).
