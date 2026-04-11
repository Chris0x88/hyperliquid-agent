# Data Layer Assessment — 2026-04-11

> Complete inventory of all data the system produces, stores, and reads.
> Separate concern from knowledge hierarchy (that's about docs/memory).
> This is about app data, market data, trading data, user data.

---

## Executive Summary

**96 MB total** across 2,152 JSON files, 30 JSONL files, and 4 SQLite databases.
The dominant store is `data/memory/` (64 MB) — mostly hourly SQLite backups.
All storage is file-based (JSON/JSONL/SQLite), local only, no external DB.

The system has **implicit backup** via memory_backup iterator (hourly snapshots
with 24h/7d/4w retention tiers) but **no formal archival** for JSONL files.
Growth is manageable today (~96 MB) but append-only JSONL files will need
rotation as trading volume scales.

**Future integration path**: NautilusTrader's data catalog for market data
(Parquet/Feather for tick data, standardized instrument definitions). The
current file-based layer was designed with this swap in mind — `web/api/readers/`
has abstract interfaces.

---

## Data Inventory by Category

### 1. Market Data (5.4 MB)

| File | Format | Size | Writer | Reader | Growth |
|------|--------|------|--------|--------|--------|
| `data/candles/candles.db` | SQLite | 1.4 MB | connector iterator + API backfill | All chart/analysis tools | Grows with markets watched |
| `data/candles/candles.db-wal` | SQLite WAL | ~4 MB | SQLite WAL | Automatic | Checkpointed periodically |

**Current state**: OHLCV candles only. No raw tick data stored. No L2 book
snapshots persisted (heatmap reads live, writes zones/cascades to JSONL).

**Growth projection**: ~100 KB/month per market at current watch frequency.
6 markets × 12 months ≈ 7 MB/year. Negligible.

**Nautilus integration point**: Replace `candles.db` with NautilusTrader's
`ParquetDataCatalog`. Standardized `Bar` objects, instrument definitions,
and the `DataCatalog` API would give us tick-level storage + multi-timeframe
aggregation for free. The `web/api/readers/CandleCache` interface is already
abstract enough to swap.

---

### 2. Trading Data (8.5 MB)

| File | Format | Size | Writer | Reader | Growth |
|------|--------|------|--------|--------|--------|
| `data/research/journal.jsonl` | JSONL | ~50 KB | Multiple strategies (on close) | lesson_author, AI agent | Append-only, ~1 entry per closed trade |
| `data/strategy/oil_botpattern_journal.jsonl` | JSONL | ~100 KB | oil_botpattern iterator | `/oilbotjournal`, AI, self-tune | Append-only, ~1 entry per decision |
| `data/strategy/oil_botpattern_state.json` | JSON | ~4 KB | oil_botpattern iterator | `/oilbot`, web dashboard | Overwritten each tick |
| `data/strategy/oil_botpattern_shadow_positions.json` | JSON | ~2 KB | oil_botpattern (shadow) | `/sim` | Overwritten each tick |
| `data/strategy/oil_botpattern_shadow_trades.jsonl` | JSONL | ~20 KB | oil_botpattern (shadow) | `/sim` | Append-only |
| `data/strategy/oil_botpattern_shadow_balance.json` | JSON | ~1 KB | oil_botpattern (shadow) | `/sim` | Overwritten each tick |
| `data/strategy/oil_botpattern_adaptive_log.jsonl` | JSONL | ~200 KB | adaptive evaluator | Diagnostic | Append-only |
| `data/strategy/oil_botpattern_tune_audit.jsonl` | JSONL | ~5 KB | self-tune L1 | `/selftune` | Append-only |
| `data/strategy/oil_botpattern_proposals.jsonl` | JSONL | ~5 KB | self-tune L2 | `/selftuneproposals` | Append-only |
| `data/strategy/oil_botpattern_shadow_evals.jsonl` | JSONL | ~5 KB | self-tune L4 | `/shadoweval` | Append-only |
| `data/snapshots/` | JSON | 6.4 MB | account_collector | Equity curve, web dashboard | ~1 snapshot per tick |
| `data/daemon/journal/ticks*.jsonl` | JSONL | ~500 KB | daemon clock | Diagnostic | Daily rotation (ticks-YYYYMMDD.jsonl) |

**Rotation needed**: `data/snapshots/` at 6.4 MB and growing. Should implement
a retention policy (keep 30 days, archive older to compressed files).

**Nautilus integration point**: `journal.jsonl` maps to NautilusTrader's
`OrderFilled` / `PositionClosed` events. The `TradingNode` event store would
give us proper backtesting infrastructure. Major refactor but the data format
is close enough for a migration script.

---

### 3. News & Intelligence Data (1.0 MB)

| File | Format | Size | Writer | Reader | Growth |
|------|--------|------|--------|--------|--------|
| `data/news/headlines.jsonl` | JSONL | ~10 KB | news_ingest | Diagnostic | Append-only, ~89 lines |
| `data/news/catalysts.jsonl` | JSONL | ~20 KB | news_ingest | supply_ledger, bot_classifier, catalyst_deleverage | Append-only |
| `data/supply/state.json` | JSON | ~4 KB | supply_ledger | oil_botpattern, `/supply` | Overwritten periodically |
| `data/daemon/supply_disruptions.jsonl` | JSONL | ~5 KB | supply_ledger | `/disruptions` | Append-only |
| `data/heatmap/zones.jsonl` | JSONL | ~600 KB | heatmap | oil_botpattern, `/heatmap` | Append-only, 2,627 lines |
| `data/heatmap/cascades.jsonl` | JSONL | ~50 KB | heatmap | bot_classifier | Append-only |
| `data/research/bot_patterns.jsonl` | JSONL | ~80 KB | bot_classifier | oil_botpattern, `/botpatterns` | Append-only, 446 lines |

**Growth concern**: `data/heatmap/zones.jsonl` at 600 KB with 2,627 lines is
the fastest-growing intelligence file. At current rate, ~1 MB/month. Needs
rotation after a year.

---

### 4. User Data (10 MB)

| File | Format | Size | Writer | Reader | Growth |
|------|--------|------|--------|--------|--------|
| `data/daemon/chat_history.jsonl` | JSONL | ~50 KB | telegram_agent | AI agent (context), `/chathistory` | Append-only, 355 lines |
| `data/diagnostics/chat_log.jsonl` | JSONL | ~30 KB | telegram_bot (diag) | Diagnostic | Append-only, 371 lines |
| `data/daemon/feedback.jsonl` | JSONL | ~5 KB | `/feedback` command | AI sessions, diagnostic | Append-only |
| `data/daemon/bugs.jsonl` | JSONL | ~2 KB | `/bug` command | AI sessions | Append-only |
| `data/daemon/todos.jsonl` | JSONL | ~2 KB | `/todo` command | AI sessions | Append-only |
| `data/agent_memory/MEMORY.md` | Markdown | ~2 KB | AI agent | AI agent | Edited in place |

**Privacy note**: Chat history contains user messages and AI responses. All
local-only (never sent anywhere). No PII beyond what the user types.

**Feedback pipeline**: `/feedback` → `data/daemon/feedback.jsonl` (raw, permanent)
→ AI session may promote to memory file (distilled, durable preference).

---

### 5. Memory & Learning Data (64 MB — largest category)

| File | Format | Size | Writer | Reader | Growth |
|------|--------|------|--------|--------|--------|
| `data/memory/memory.db` | SQLite FTS5 | 1.9 MB | AI agent (lessons), daemon (events, learnings) | AI agent tools, `/lessons`, `/lessonsearch` | Grows with lessons + events |
| `data/memory/backups/` | SQLite copies | ~60 MB (30+ copies) | memory_backup iterator | Emergency restore | Hourly, 24h/7d/4w retention |
| `data/memory/working_state.json` | JSON | ~4 KB | daemon | All components | Overwritten each tick |
| `data/research/learnings.md` | Markdown | ~10 KB | memory_consolidation | lesson_author, AI agent | Append + trim |
| `data/research/entry_critiques.jsonl` | JSONL | ~20 KB | entry_critic iterator | `/critique` | Append-only |
| `data/daemon/lesson_candidates/*.json` | JSON files | ~20 KB | lesson_author | `/lessonauthorai` | One file per closed trade |
| `data/reviews/brutal_review_*.md` | Markdown | ~30 KB | `/brutalreviewai` | User | One file per review |

**The 64 MB elephant**: `data/memory/backups/` has 30+ SQLite copies at ~1.8 MB
each. The memory_backup iterator runs hourly with retention tiers (24h hourly,
7d daily, 4w weekly). This is BY DESIGN — crash-safe atomic snapshots.

**Optimization**: The backup retention could be more aggressive (keep 12 hourly,
7 daily, 4 weekly = max 23 copies × 2 MB = 46 MB ceiling). Currently it seems
to be keeping more than the stated policy.

---

### 6. Thesis & Conviction Data (148 KB)

| File | Format | Size | Writer | Reader | Growth |
|------|--------|------|--------|--------|--------|
| `data/thesis/btc_perp_state.json` | JSON | 3.7 KB | AI agent | thesis_engine, execution_engine | Overwritten on update |
| `data/thesis/xyz_brentoil_state.json` | JSON | 1.1 KB | AI agent | thesis_engine, oil_botpattern | Overwritten on update |
| `data/thesis/xyz_cl_state.json` | JSON | 5.1 KB | AI agent | thesis_engine | Overwritten on update |
| `data/thesis/xyz_gold_state.json` | JSON | 3.6 KB | AI agent | thesis_engine | Overwritten on update |
| `data/thesis/xyz_silver_state.json` | JSON | 3.4 KB | AI agent | thesis_engine | Overwritten on update |
| `data/thesis/xyz_sp500_state.json` | JSON | 3.8 KB | AI agent | thesis_engine | Overwritten on update |
| `data/thesis/challenges.jsonl` | JSONL | 120 KB | thesis_challenger | `/thesis`, diagnostic | Append-only, 258 lines |

**Note**: Thesis files are the shared contract between user and system. Small,
critical, overwritten. The challenges log tracks when catalysts match
invalidation conditions.

---

### 7. Config Data (100 KB)

25 files in `data/config/`. Already documented in architecture assessment.
Now validated by Pydantic schemas in `common/config_schema.py`.

---

### 8. Research & Signals (5.8 MB)

| File | Format | Size | Writer | Reader | Growth |
|------|--------|------|--------|--------|--------|
| `data/research/markets/xyz_brentoil/signals.jsonl` | JSONL | ~500 KB | radar/pulse | `/signals`, AI agent | Append-only, 8,956 lines |
| `data/research/evaluations/*.json` | JSON | ~5 MB (2,000+ files) | trade_evaluator | AI agent context | One file per evaluation |

**Growth concern**: `data/research/evaluations/` has 2,000+ timestamped JSON
files totaling ~5 MB. No archival strategy. These are deterministic trade setup
evaluations — useful for backtesting but growing unbounded.

---

## Summary Table

| Category | Size | Files | Growth Rate | Rotation? |
|----------|------|-------|-------------|-----------|
| Market (candles) | 5.4 MB | 3 | ~100 KB/mo/market | No (SQLite) |
| Trading (journals, state) | 8.5 MB | 15+ | ~200 KB/mo | Tick JSONL daily-rotated |
| News & Intelligence | 1.0 MB | 7 | ~100 KB/mo | No (needs it) |
| User (chat, feedback) | 0.1 MB | 6 | ~10 KB/mo | No |
| Memory & Learning | 64 MB | 30+ | ~2 MB/day (backups) | Hourly with retention tiers |
| Thesis & Conviction | 0.15 MB | 7 | Negligible | No |
| Config | 0.1 MB | 25 | Static | No |
| Research & Signals | 5.8 MB | 2,000+ | ~1 MB/mo | **NO — needs archival** |
| **Total** | **96 MB** | **~2,200** | **~5 MB/mo** | |

---

## Data Growth Projections

| Timeframe | Projected Size | Driver |
|-----------|---------------|--------|
| 6 months | ~130 MB | Research evaluations + memory backups |
| 1 year | ~170 MB | JSONL files + evaluations |
| 2 years | ~260 MB | Linear growth, no archival |
| With Nautilus | Variable | Tick data could be 10-100x larger |

At current rates, the file-based system handles years of operation without
stress. The bottleneck is not size but QUERYABILITY — JSONL files require
full scans. SQLite (candles.db, memory.db) handles queries efficiently.

---

## Nautilus Integration Path

NautilusTrader's data infrastructure offers three things this system lacks:

1. **Tick-level storage**: `ParquetDataCatalog` for `QuoteTick`, `TradeTick`,
   `Bar` objects. Currently we only store OHLCV candles.

2. **Standardized instrument definitions**: `Instrument` objects with proper
   venue, symbol, tick size, lot size. Currently we handle this ad-hoc in
   `markets.yaml` + `common/markets.py`.

3. **Event store**: `OrderFilled`, `PositionChanged`, `PositionClosed` events
   with proper sequencing. Currently in `journal.jsonl` as ad-hoc JSON.

**Integration strategy** (when ready):
- Phase 1: Use `ParquetDataCatalog` for candle storage (replace candles.db)
- Phase 2: Map `journal.jsonl` entries to Nautilus `Position` events
- Phase 3: Full `TradingNode` integration for backtesting + live execution

**The current file-based system is a valid stepping stone.** The abstract
`web/api/readers/` interfaces were designed with this swap in mind. Don't
rush it — the file-based layer works and is debuggable.

---

## Recommendations

### P0 — Quick Wins

1. **Enforce memory backup retention**: Verify the backup iterator respects
   the 24h/7d/4w policy. Current 30+ copies at 60 MB suggests drift.

2. **Add rotation to heatmap zones**: `zones.jsonl` at 2,627 lines and growing.
   Monthly rotation with date suffix (zones-2026-04.jsonl).

### P1 — Medium Term

3. **Archive research evaluations**: Move evaluations older than 30 days to
   `data/research/evaluations/archive/YYYY-MM/`. Keep recent for AI context.

4. **Add size monitoring**: A simple script that reports `du -sh data/*/` and
   flags directories exceeding thresholds.

### P2 — When Scaling

5. **Nautilus Phase 1**: Replace candles.db with ParquetDataCatalog when tick
   data becomes necessary for strategy development.

6. **JSONL → SQLite migration**: Move high-query files (bot_patterns, signals,
   challenges) into memory.db or a dedicated analytics.db. JSONL is fine for
   append-only audit logs but bad for time-range queries.

---

*Generated 2026-04-11. Data sizes measured from live filesystem.*
