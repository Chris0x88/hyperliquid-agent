# ADR-011: Two-App Architecture — Research Sibling with Nautilus Catalog

**Date:** 2026-04-07
**Status:** Proposed (planning only — no code yet)
**Supersedes:** Aspects of MASTER_PLAN.md Phase 3 sequencing
**Related:** ADR-002 (conviction engine), ADR-009 (embedded agent runtime)

## Context

### What we have today

The trading bot (`agent-cli/`) is a mature, running system: WATCH-tier daemon, Telegram bot, embedded AI agent runtime, conviction engine, on-exchange stops, vault rebalancer, comprehensive test suite (`pytest -x -q`). Architecturally it serves three roles in one process tree: portfolio copilot, research agent, and risk manager.

Storage today is fragmented across six formats:

| Format | Location | Holds |
|---|---|---|
| SQLite | `data/memory/memory.db` | Events, learnings, summaries, observations, action_log, execution_traces |
| SQLite | `data/candles/candles.db` | OHLCV candle cache |
| JSON files | `data/snapshots/*.json` | Account snapshots (one file per tick, growing unbounded — see directory) |
| JSON files | `data/thesis/*.json` | Thesis state per market |
| JSONL | `data/daemon/chat_history.jsonl` | Telegram chat log |
| JSONL | `data/apex/journal.jsonl` | Trade journal |
| Markdown | `data/agent_memory/*.md` | Agent persistent memory |

Strategy code lives in `agent-cli/strategies/` — see the directory for the full list. Each file is real Python (EMA/RSI/ATR math, state machines, scale-in logic, ATR-trailing stops), not LLM prompts. Of these, only `claude_agent.py` is wired into the daemon today. The rest are dormant but functional. **None should be deleted.**

The decision engine `modules/apex_engine.py` is a stateless function that already accepts a `strategy_signals` parameter — it was designed for signal stacking but the bridge from strategy code to APEX signal rows was never built.

The REFLECT/JOURNAL/MEMORY engines (`modules/reflect_engine.py`, `journal_engine.py`, `memory_engine.py`) are CLI-only. The Phase 3 plan to wire them into the daemon was specced (`docs/plans/PHASE_3_REFLECT_LOOP.md`) but never shipped.

The daily report generator (`cli/daily_report.py`) exists, produces a 1-page PDF, but has hardcoded thesis text and catalysts and has been run exactly once (one PDF in `data/reports/` from 2026-03-30).

### What Chris wants

Stated explicitly across this planning session:

1. A real database for everything we track (not scattered files).
2. A programmatic decision engine that combines/multiplies multiple signals into actions — not AI-driven trading.
3. Daily reports that drive a daily decision ritual.
4. Big-dataset capable (years of history, multiple markets, room for ML feature columns).
5. Serious-but-infrequent ML (weekly/monthly retraining, high quality).
6. Hardened, best-of-breed OSS patterns. No reinventing.
7. Don't destroy what's already working. Don't delete strategy code.
8. AI is for research and conversation, eventually removable from the trading path.

### Why a single integrated build is the wrong answer

The natural temptation is to extend the existing bot — add more iterators, more tables, more responsibilities. We have rejected this approach for six reasons, in order of impact on Chris's P&L:

1. **The bot works.** Touching the conviction engine, guards, or daemon clock to add features risks regressing code that is currently keeping Chris solvent. The single biggest threat to profit is regression in safety code, not absence of features.
2. **Decision cadence is slow.** Daily review + weekly thesis updates + weekly/monthly ML retraining means there is **zero latency requirement** between research and execution. The only argument for tight integration (low latency) does not apply.
3. **Nautilus is opinionated.** Embedding Nautilus inside the existing daemon means fighting its `MessageBus` and `Actor` model for ownership of the event loop. As a sibling app it is a joy. As a guest it is a war.
4. **Research has no home today.** Chris's petroleum-engineering thinking is currently scattered across Telegram chats, thesis JSONs, and memory. Giving it a structured workspace (notebooks, catalog, backtests, feature pipelines) is itself a profit lever.
5. **The bot can finally be slimmed.** The 18 dormant strategies, the orphaned `quoting_engine/`, and unused signal modules can migrate to the research app where they belong. The bot becomes leaner without losing the IP.
6. **Ownership and hireability.** Two well-bounded apps can be worked on independently. If Chris ever brings in help, the research app is a clean junior-friendly thing that never touches production.

## Decision

**Build a sibling research-and-signals application (`quant/`) inside the existing `HyperLiquid_Bot/` repository, alongside `agent-cli/`. The two apps communicate through a file-based contract using a shared Parquet data catalog (Nautilus convention) plus a small signals output. The trading bot keeps execution, risk management, and Telegram I/O. The research app owns data ingestion, signal computation, backtesting, ML, and report generation. Neither app is allowed to take responsibility from the other.**

Specifically:

1. **Two apps, one repo, sibling directories.** `HyperLiquid_Bot/agent-cli/` (existing trading bot, slimmed over time) and `HyperLiquid_Bot/quant/` (new research app). Same repo for coordination ease; distinct top-level directories so test suites, dependencies, and lint configs are separate.

2. **Parquet data catalog in `HyperLiquid_Bot/quant/catalog/`.** Nautilus-style partitioning by instrument, kind, and time. Becomes the source of truth for snapshots, candles, fills, signals, features, and (eventually) ML predictions. Both apps may read; only the `quant/` app writes (with one exception — the bot dual-writes its own observations during the migration window, see Five Rules below).

3. **Signal contract = Parquet files in `quant/catalog/signals/`** plus a tiny `quant/state/signals_latest.parquet` snapshot that the bot polls each tick. APEX consumes signal rows the same way it currently consumes pulse and radar in-memory results.

4. **Daily report contract = PDF files in `quant/reports/`.** The bot reads the latest report path and forwards it to Telegram via launchd-scheduled job. No code in the bot generates report content.

5. **Nautilus is the data + research engine.** It is **not** the live execution engine. The existing `parent/hl_proxy.py` continues to handle HyperLiquid I/O. We may write a thin Nautilus adapter for HL later, but only inside the research app for backtesting purposes.

6. **Strategies migrate from autonomous traders to signal generators.** Each existing strategy file in `agent-cli/strategies/` gets a sibling adapter in `quant/src/signals/strategies/` that exposes `populate_signals(candles_df) -> DataFrame` (Freqtrade-style). The original files in `agent-cli/strategies/` are **not deleted, not moved, not modified**. They stay where they are for the duration of this project. Only after the adapters prove out in production for 30+ days do we discuss what to do with the originals.

7. **No new SQLite databases.** We extend `memory.db` with thesis_history and trade_journal tables (small, transactional), and use the catalog Parquet for everything else (large, append-only). Two storage tools, each used for what it's good at.

8. **Tier 1 wins ship before any new app is built.** Snapshot bleeding fix, daily report made data-driven (still in the bot, temporarily), and Phase 3 REFLECT loop wiring all happen first, on the existing bot, with zero dependency on the new app. This banks safe value before architectural risk.

## Architecture

### Repo layout (target state)

```
HyperLiquid_Bot/
├── agent-cli/                              [EXISTING — slimmed over time]
│   ├── cli/                                 daemon, telegram bot, agent runtime
│   ├── common/                              shared utilities
│   ├── modules/                             engines (apex, guard, radar, pulse, reflect)
│   ├── parent/                              hl_proxy, risk_manager
│   ├── strategies/                          ← stays untouched, every file preserved
│   ├── data/
│   │   ├── memory/memory.db                 ← extended with thesis_history, trade_journal
│   │   ├── candles/candles.db               ← stays as-is
│   │   ├── thesis/*.json                    ← stays as-is (the AI/Chris write contract)
│   │   └── reports/                         ← read-only mirror of quant/reports/
│   ├── docs/
│   │   ├── plans/                           phase plans (existing)
│   │   └── wiki/                            tracked per MAINTAINING.md
│   └── tests/
│
└── quant/                                  [NEW — research & signals app]
    ├── catalog/                             Parquet data catalog (Nautilus convention)
    │   ├── candles/instrument=.../interval=.../year=.../month=...
    │   ├── snapshots/instrument=.../year=.../month=...
    │   ├── fills/instrument=.../year=.../month=...
    │   ├── signals/strategy=.../instrument=.../year=.../month=...
    │   ├── features/feature_set=.../year=.../month=...
    │   └── predictions/model=.../version=.../year=.../month=...
    ├── state/
    │   ├── signals_latest.parquet           ← bot polls this every tick
    │   └── catalog_manifest.json            ← partition index for fast lookup
    ├── reports/
    │   └── YYYY-MM-DD_morning.pdf           ← bot reads + forwards to Telegram
    ├── src/
    │   ├── ingest/                          writes to catalog from HL API + bot mirror
    │   ├── signals/
    │   │   ├── adapters/                    one adapter per strategies/*.py file
    │   │   ├── pulse_signals.py             ports pulse_engine outputs to catalog
    │   │   ├── radar_signals.py             ports radar_engine outputs to catalog
    │   │   └── registry.py                  signal registry (name, owner, schema)
    │   ├── backtest/                        Nautilus backtest harness
    │   ├── ml/
    │   │   ├── features/                    feature engineering pipelines
    │   │   ├── models/                      trained model artifacts
    │   │   └── train.py                     weekly retrain entry point
    │   ├── reports/
    │   │   └── daily_report.py              data-driven report generator (replaces bot's)
    │   ├── api/
    │   │   └── publish_signals.py           writes signals_latest.parquet
    │   └── research/                        notebooks, scratch
    ├── notebooks/                           Jupyter notebooks for ad-hoc research
    ├── tests/
    ├── pyproject.toml                       independent dependency set
    └── README.md
```

### Process model

```
                ┌───────────────────────────┐
                │  HyperLiquid Exchange     │
                └──────────┬────────────────┘
                           │ HL REST/WS
              ┌────────────┴────────────┐
              │                         │
   ┌──────────▼──────────┐    ┌────────▼─────────────┐
   │   agent-cli (bot)   │    │ quant/ingest         │
   │   - Daemon          │    │ - Pulls candles/L2   │
   │   - Telegram        │    │ - Writes catalog     │
   │   - Conviction      │    │ - launchd scheduled  │
   │   - Guards/stops    │    └──────────┬───────────┘
   │   - APEX execution  │               │
   └──────┬──────────────┘               │
          │                              │
          │ writes own fills/positions   │ writes candles/snapshots
          │ to catalog (dual-write)      │ to catalog
          │                              │
          └──────────┬───────────────────┘
                     │
         ┌───────────▼─────────────────┐
         │  quant/catalog (Parquet)    │
         │  Single source of truth     │
         └───────────┬─────────────────┘
                     │
        ┌────────────┼────────────────────┐
        │            │                    │
┌───────▼──────┐ ┌──▼───────────┐ ┌──────▼──────────┐
│ signals/     │ │ backtest/    │ │ ml/             │
│ - Strategies │ │ - Nautilus   │ │ - Weekly train  │
│ - Pulse      │ │ - Hyperopt   │ │ - Predictions   │
│ - Radar      │ │              │ │   to catalog    │
└──────┬───────┘ └──────────────┘ └─────────────────┘
       │
       │ writes signals.parquet partitions
       │ + signals_latest.parquet snapshot
       ▼
┌──────────────────────┐
│  bot polls each tick │  ← APEX iterator reads signals_latest.parquet
│  no IPC, no HTTP     │     and feeds rows into apex_engine.evaluate(...)
└──────────────────────┘
```

The bot and the research app communicate exclusively through files in `quant/catalog/`, `quant/state/`, and `quant/reports/`. Both apps degrade independently: if the research app is offline, the bot uses the last signals it has. If the bot is offline, the research app keeps building data.

### Data layer design

**Parquet catalog partitioning** (Nautilus convention, Hive-style):

| Path pattern | Owner | Read by | Schema notes |
|---|---|---|---|
| `candles/instrument={}/interval={}/year={}/month={}/data.parquet` | `quant/ingest` | bot, signals, ml, backtest | OHLCV + funding + OI columns |
| `snapshots/instrument={}/year={}/month={}/data.parquet` | bot (dual-write) | all | Position state, equity, margin per tick |
| `fills/instrument={}/year={}/month={}/data.parquet` | bot (dual-write) | journal, reflect, ml | One row per fill, side, size, price, fees |
| `signals/strategy={}/instrument={}/year={}/month={}/data.parquet` | `quant/signals` | bot (APEX) | timestamp, score, direction, metadata |
| `features/feature_set={}/year={}/month={}/data.parquet` | `quant/ml` | training, prediction | Engineered features by candle timestamp |
| `predictions/model={}/version={}/year={}/month={}/data.parquet` | `quant/ml` | bot (optional), research | Model output by candle timestamp |

**SQLite (`memory.db`) extensions** (small, transactional, no Parquet needed):

```sql
-- New table: thesis_history (immutable audit log of thesis changes)
CREATE TABLE IF NOT EXISTS thesis_history (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp_ms  INTEGER NOT NULL,
    market        TEXT NOT NULL,
    direction     TEXT NOT NULL,
    conviction    REAL NOT NULL,
    take_profit   REAL,
    leverage      REAL,
    size_pct      REAL,
    evidence_for  TEXT,                          -- JSON array
    evidence_against TEXT,                       -- JSON array
    invalidation  TEXT,                          -- JSON array
    source        TEXT NOT NULL,                 -- "manual", "agent", "research"
    notes         TEXT
);
CREATE INDEX IF NOT EXISTS idx_thesis_history_market_ts
    ON thesis_history(market, timestamp_ms);

-- New table: trade_journal (FIFO round-trip outcomes)
CREATE TABLE IF NOT EXISTS trade_journal (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    open_ts_ms    INTEGER NOT NULL,
    close_ts_ms   INTEGER NOT NULL,
    instrument    TEXT NOT NULL,
    direction     TEXT NOT NULL,
    size          REAL NOT NULL,
    entry_price   REAL NOT NULL,
    exit_price    REAL NOT NULL,
    fees          REAL NOT NULL DEFAULT 0,
    pnl           REAL NOT NULL,
    roe_pct       REAL,
    holding_ms    INTEGER NOT NULL,
    entry_source  TEXT,                          -- which signal/strategy triggered entry
    exit_reason   TEXT,                          -- "trailing_stop", "thesis_invalidated", etc.
    signal_score  REAL,                          -- score at time of entry
    thesis_id     INTEGER,                       -- FK to thesis_history.id at time of entry
    quality       TEXT,                          -- "good", "fair", "poor"
    retrospective TEXT                           -- AI-generated lessons after the fact
);
CREATE INDEX IF NOT EXISTS idx_trade_journal_instrument_ts
    ON trade_journal(instrument, close_ts_ms);
```

These two tables live in the existing `memory.db` because they are small, transactional, and naturally relational. Everything append-only and large goes in the catalog.

### Signal contract

Every signal row in `quant/catalog/signals/` and the snapshot file `signals_latest.parquet` follows this schema:

| Column | Type | Notes |
|---|---|---|
| `timestamp_ms` | int64 | Time the signal was computed |
| `instrument` | string | e.g. `xyz:BRENTOIL`, `BTC` |
| `strategy_id` | string | Which strategy adapter produced this row (e.g. `brent_oil_squeeze`, `pulse`, `radar`) |
| `signal_name` | string | Specific named signal within the strategy (e.g. `dip_buy_21ema`, `oi_agreement_long`) |
| `direction` | string | `long`, `short`, `neutral`, `exit_long`, `exit_short` |
| `score` | float64 | Strength of signal in [0.0, 1.0] |
| `confidence` | float64 | Strategy's own confidence in this signal in [0.0, 1.0] |
| `horizon_ms` | int64 | How long this signal is valid for |
| `entry_hint` | float64 | Suggested entry price (or null) |
| `stop_hint` | float64 | Suggested stop price (or null) |
| `tp_hint` | float64 | Suggested take-profit (or null) |
| `metadata` | string | JSON blob of strategy-specific context |
| `regime_tags` | list[string] | e.g. `["weekend", "low_liq"]`, `["bullish_trend"]` |

APEX consumes the latest `signals_latest.parquet` each tick, filters by freshness and instrument, combines via the rules engine (Phase 3), and emits trade intents.

This is the **Freqtrade-pattern signal layer expressed as Parquet** instead of an in-process DataFrame. APEX is the only component that turns signals into orders.

## The Five Rules (safety guarantees)

These are non-negotiable for the duration of the project. They exist so we never destroy the running system.

1. **Additive only.** New tables, new modules, new files. We never delete or overwrite existing data, files, or modules without explicit confirmation in chat. The 1200 snapshot JSONs stay on disk; we just stop adding new ones once the catalog is proven.
2. **Dual-write before cutover.** When a producer moves from JSON to catalog, it writes BOTH for at least 7 days. Only after we verify the catalog matches the JSONs row-for-row do we stop writing JSONs. Even then, the existing files stay on disk.
3. **Read-path migrations are independent.** Each consumer (Telegram bot, daily report, agent context, REFLECT engine) gets migrated to read from the catalog one at a time. The old code path stays as a fallback for at least one release after the new one ships.
4. **Strategy files in `agent-cli/strategies/` are not deleted, moved, or modified for the duration of this project.** Adapters are written in `quant/src/signals/adapters/` that import from the originals. The originals are read-only canon.
5. **Every phase ends in a working system.** No "halfway" states. If the project is paused mid-phase, the bot still runs exactly as it does today.

## Phased plan

The plan is structured in four tiers. Tier 1 ships entirely on the existing bot before any new app code is written. Tiers 2-4 build the research app incrementally and migrate consumers one at a time.

### Tier 1 — Bank the small wins (no new app, all in `agent-cli/`)

**Goal:** Stop the snapshot bleeding, ship a daily report Chris actually receives, and close the learning loop. All on the existing bot. Zero architectural risk.

**T1.1 Snapshot consolidation**
- Add a `account_snapshots` table to `memory.db`.
- Modify the `account_collector` iterator to write rows to the table in addition to the JSON files.
- After 7 days of dual-write verification, stop writing new JSON files. Existing files remain on disk (Rule 1).
- No reads change. The bot still reads from the in-memory `TickContext`. The table is the new home for *historical* snapshots; tick-time state is unchanged.
- Acceptance: zero JSON files added per day, table has continuous coverage from cutover, bot tests still green.

**T1.2 Data-driven daily report (still in the bot)**
- Rewrite `cli/daily_report.py` to read from `memory.db` (snapshots, events, learnings) and `data/thesis/*.json` instead of hardcoded text.
- Keep the existing 1-page PDF format from the 2026-03-30 reference report; add a "Yesterday vs 7-day average" section.
- Add a launchd plist to run it at 06:30 AEST and post to Telegram via existing helpers.
- The hardcoded catalysts section becomes a dynamic query against `events` table filtered by `event_type='catalyst'`.
- The hardcoded thesis section reads from the actual thesis JSON files.
- Acceptance: a fresh PDF lands in Telegram every morning at 06:30 AEST for 7 consecutive days, content reflects current state.

**T1.3 Wire the Phase 3 REFLECT loop**
- Per `docs/plans/PHASE_3_REFLECT_LOOP.md`, build the `reflect` and `journal` daemon iterators.
- On every position close (detected by `guard` or `execution_engine`), append a `JournalEntry` row to the new `trade_journal` table in `memory.db`.
- Nightly at 23:30 AEST: `reflect` iterator runs `ReflectEngine.compute()` on the past 24h of journal entries, logs `ReflectMetrics` to `events` table, sends a brief Telegram message ("Today: 3 trades, 67% WR, +$45 | 7d avg: 55% WR, +$23/day").
- Weekly on Sunday: `ReflectReporter.distill()` produces a summary, sent to Telegram.
- Acceptance: at least one full nightly cycle runs and produces a Telegram message; trade_journal table has entries for any trades that closed.

**T1.4 Decision ritual operationalized**
- Define the morning ritual as a documented Claude Code session: read the daily report, check signal stack, review yesterday's reflect output, decide on thesis updates, write thesis JSON files. (No new code — this is process.)
- Acceptance: documented in `docs/wiki/operations/decision-ritual.md` (new wiki page).

**Tier 1 stops here.** Chris evaluates whether the daily ritual feels right and the reflect loop produces useful output. **Only if Tier 1 lands cleanly do we proceed to Tier 2.**

### Tier 2 — Stand up the research app shell

**Goal:** Build `quant/` as an empty but real app. Establish the catalog. Dual-write candles and snapshots. No new behavior, just the storage backbone proven.

**T2.1 Bootstrap `quant/` directory**
- Create `quant/` with sibling structure as in repo layout.
- Independent `pyproject.toml` with NautilusTrader, polars or pyarrow, jupyter, and minimal deps.
- Independent test suite (`quant/tests/`).
- Add `quant/CLAUDE.md` routing file per MAINTAINING.md conventions.
- Acceptance: `cd quant && pytest` runs (with zero tests initially), `cd quant && python -c "import nautilus_trader"` succeeds.

**T2.2 Catalog ingestion: candles**
- Build `quant/src/ingest/candles.py` that pulls candles from HL API and writes to `quant/catalog/candles/` partitioned by instrument/interval/year/month.
- Run as a launchd job every 5 minutes for the watchlist instruments.
- Backfill historical candles from `agent-cli/data/candles/candles.db` (one-time migration script).
- Acceptance: catalog has continuous candle coverage for all watchlist instruments, partitions exist on disk, can be loaded with `pl.scan_parquet()`.

**T2.3 Catalog ingestion: snapshots and fills (dual-write from bot)**
- Modify the bot's `account_collector` iterator to also write account snapshots to `quant/catalog/snapshots/`.
- Modify the bot's `execution_engine` iterator to write fills to `quant/catalog/fills/` on every order completion.
- Both are best-effort writes — failure to write to the catalog must NOT break the bot. Wrap in try/except, log warnings.
- Acceptance: catalog snapshot/fill partitions match bot state for 7 consecutive days.

**T2.4 Daily report migrates to `quant/`**
- Port `cli/daily_report.py` to `quant/src/reports/daily_report.py`, reading from the catalog instead of `memory.db`.
- Bot's launchd job switches from running the bot's report generator to running the quant app's, then forwards the resulting PDF to Telegram.
- Old `cli/daily_report.py` stays in place but is no longer scheduled (Rule 1, Rule 3).
- Acceptance: PDF lands in Telegram for 7 days, content matches what the bot's version was producing.

### Tier 3 — Strategies become signal generators

**Goal:** Each dormant strategy file in `agent-cli/strategies/` becomes a signal source consumed by APEX. No strategy file is touched.

**T3.1 Signal adapter framework**
- Define the signal contract (schema in this ADR section).
- Build `quant/src/signals/registry.py` — a registry of signal sources with metadata (name, owner, schema version, freshness expectation).
- Build `quant/src/signals/adapters/base.py` — base class for adapters that wrap an existing strategy.
- Build `quant/src/api/publish_signals.py` — writes the partition + updates `signals_latest.parquet` atomically.
- Acceptance: a unit test wraps a trivial fake strategy and writes a valid partition that can be read back.

**T3.2 First adapter: `brent_oil_squeeze`**
- Build `quant/src/signals/adapters/brent_oil_squeeze.py` that imports from `agent-cli.strategies.brent_oil_squeeze` (path injection in the adapter, original file untouched).
- The adapter calls the strategy's `on_tick` with replayed candles from the catalog and translates `StrategyDecision` outputs into signal rows.
- Run as a launchd job every 5 minutes for `xyz:BRENTOIL`.
- Acceptance: signal rows appear in `quant/catalog/signals/strategy=brent_oil_squeeze/instrument=xyz_BRENTOIL/`.

**T3.3 APEX reads signals from `signals_latest.parquet`**
- Modify the bot's `apex_engine.evaluate()` call site to also pass `strategy_signals` loaded from `quant/state/signals_latest.parquet`.
- APEX already accepts this parameter — we just need to wire it.
- The bot does NOT take action on the new signals yet; we observe in WATCH mode for 7 days to verify signal quality and timing.
- Acceptance: APEX logs show signals being received and considered; no unexpected execution behavior.

**T3.4 Port remaining strategies, one per session**
- For each remaining strategy in `agent-cli/strategies/`, build an adapter in `quant/src/signals/adapters/`. Each port is its own session/PR.
- Order of priority: `oil_war_regime`, `oil_liq_sweep` (oil-focused, Chris's edge first), then `oi_divergence`, `funding_momentum`, `momentum_breakout`, `mean_reversion`, `trend_follower`, then the MM strategies (lower priority).
- `claude_agent.py` is special — it remains the AI-driven strategy and is NOT ported (it stays wired into the daemon as today).
- Acceptance: at least the oil-focused strategies are emitting signals; APEX can see them.

**T3.5 Pulse and radar engines also publish to catalog**
- Build `quant/src/signals/pulse_signals.py` and `quant/src/signals/radar_signals.py` that mirror the existing `pulse` and `radar` daemon iterators' outputs into catalog signal rows.
- This unifies all signal sources (strategies, pulse, radar, anything future) into one queryable place.
- The existing in-memory pulse/radar iterators in the bot continue to work unchanged. We dual-write.
- Acceptance: catalog signals partition has rows from pulse and radar in addition to strategies.

### Tier 4 — Decision rules engine and ML

**Goal:** APEX combines stacked signals via explicit weighted rules. Then a weekly ML model learns better weights.

**T4.1 Decision rules formalized**
- Document the decision math in a new ADR (ADR-012 likely): how signals combine (weighted sum? multiplicative? max-of? regime-gated?), how conviction bands interact with signal scores, how calendar/regime vetoes apply.
- Implement in `agent-cli/modules/apex_engine.py` as new methods. Existing methods unchanged (Rule 1).
- Configurable per-instrument weights stored in `agent-cli/data/cli/config/apex_weights.json`.
- Acceptance: APEX can run in either "legacy" mode (current behavior) or "stacked" mode (new behavior) under a feature flag.

**T4.2 Backtesting harness in `quant/`**
- Build `quant/src/backtest/` using NautilusTrader's `BacktestEngine`.
- Replay catalog candles + signal rows, simulate APEX decision logic, compute P&L.
- Compare backtest outputs to actual `trade_journal` for the same period to validate accuracy.
- Acceptance: backtest of past 30 days reproduces actual trades within reasonable tolerance.

**T4.3 Feature pipeline**
- Build `quant/src/ml/features/` that computes ML features from catalog data: rolling returns, volatility, regime tags, signal histories, calendar context.
- Store as `quant/catalog/features/` partitions.
- Acceptance: weekly job runs and produces a feature partition for the past week.

**T4.4 First ML model: signal weight learner**
- Build `quant/src/ml/train.py` that trains a model (start with LightGBM) to predict trade-level P&L given the signal stack at entry time.
- Output: revised per-signal weights for APEX.
- Run weekly. Outputs to `quant/catalog/predictions/model=signal_weighter/version=YYYY-WW/`.
- APEX optionally loads the latest version under a feature flag.
- Acceptance: a trained model exists, predictions are written, walk-forward validation shows non-trivial signal vs random baseline.

**T4.5 Hyperopt integration (optional, late-stage)**
- Add NautilusTrader-driven hyperopt over strategy parameters using historical catalog data.
- Lowest priority. Only if Tier 4 work to date has produced meaningful improvements and Chris wants to push further.

### Phase ordering and gates

```
Tier 1  (existing bot only) ─────► gate: 7 days of clean daily reports + reflect output
   │
   ▼
Tier 2  (research app shell + catalog) ─────► gate: catalog matches bot state for 7 days
   │
   ▼
Tier 3  (strategies as signals, observe-only in APEX) ─────► gate: signal quality reviewed
   │
   ▼
Tier 4  (rules engine + ML) ─────► no further gate, ongoing iteration
```

**Each gate is a manual checkpoint with Chris.** No tier starts without explicit approval at the gate.

## Open questions (deferred to implementation phase)

These are real questions but they don't block the spec. We resolve them in their respective phases.

1. **Polars vs PyArrow vs pandas for the catalog read path.** Polars is fastest and cleanest; pandas has the most ecosystem; PyArrow is what Nautilus uses internally. **Tentative answer:** Polars for new code, PyArrow for the Nautilus interop layer, pandas only where a downstream library demands it. Decided in T2.1.
2. **NautilusTrader version pinning.** Nautilus is moving fast; we want a stable version, not bleeding edge. Decided at T2.1 based on what's current at the time.
3. **HL adapter for Nautilus.** Needed for Tier 4 backtesting to use Nautilus's `BacktestEngine` natively. Could be deferred by feeding catalog data into Nautilus via custom data loaders. Decided in T4.2.
4. **Signal scoring scale.** [0.0, 1.0] is the placeholder. Could be [-1.0, 1.0] with sign indicating direction, or a separate `score` + `direction` columns (current spec). Decided in T3.1.
5. **Catalog partitioning granularity.** Year/month is the default; might need year/month/day for high-frequency data. Decided in T2.2 based on actual data volumes.
6. **How APEX combines signals mathematically.** Weighted sum vs multiplication vs max vs Bayesian — decided in T4.1 with its own ADR (ADR-012).
7. **What happens to `agent-cli/strategies/` long-term.** Decision deferred to 30 days after T3.4 completes. Default: stays where it is forever as the canonical source.
8. **`tmp_architecture.md` cleanup.** This scratch file at repo root is a near-duplicate of `docs/wiki/architecture/current.md`. **Not deleted as part of this project.** Flagged for separate cleanup at Chris's discretion.

## Consequences

### Positive

- **The bot stops accumulating responsibility.** Slimming becomes possible because every new responsibility lands in `quant/` instead.
- **Research has a real home.** Notebooks, backtests, ML experimentation all live in one place with the right tools.
- **Big-data ready from day one.** Parquet catalog scales to years of multi-instrument tick data without architectural changes.
- **ML-ready from day one.** Feature engineering reads catalog Parquet directly, no impedance.
- **Fault isolation.** Either app can be down and the other keeps working in degraded mode.
- **The dormant strategies finally do work.** Existing strategy code in `agent-cli/strategies/` becomes signal generators that APEX can stack.
- **Daily decision ritual is real.** A PDF lands every morning, a Claude Code session each day, the loop closes.

### Negative

- **Two pyproject.toml files to maintain.** Dependency management overhead. Mitigated by sibling-dir layout (one venv per app, no cross-pollution).
- **More files on disk.** Parquet partitions plus existing JSONs (during dual-write windows). Mitigated by Rule 2 dual-write windows being time-bounded.
- **Steeper learning curve for new contributors.** Two apps, one contract, Nautilus concepts. Mitigated by `quant/CLAUDE.md` routing and the research app being independently understandable.
- **More documentation surface area.** New ADRs, new wiki pages for `quant/`, updated `MASTER_PLAN.md`. Mitigated by writing each as we go and following MAINTAINING.md.
- **First-time Nautilus learning cost.** Real one-time cost. Mitigated by using Nautilus only for catalog + backtesting first, not for full strategy authoring.

### Reversible

If the research app turns out to be a mistake at any point, the bot still works. We can stop running the research app and the bot continues exactly as it does today. The only thing we will have spent is engineering time and disk space. **No live trading code is touched until Tier 3, and even there it is read-only signal consumption.**

## Compliance with project rules

Per `CLAUDE.md` core rules:

- **No destructive overreach.** Five Rules guarantee additivity. Strategy files explicitly preserved. JSON files preserved during dual-write.
- **Minimal bug fixes.** This is not a bug fix project; this is an additive feature project with careful sequencing.
- **Zero external deps by default.** Nautilus is a heavy dep but it's exactly the kind of "best of breed OSS" the user explicitly asked for. No external services (no Postgres, no Timescale, no QuestDB, no InfluxDB, no Redis, no Docker required). The catalog is just files on disk.
- **No personal data in git.** Catalog files go in `.gitignore`. Reports go in `.gitignore`. State files go in `.gitignore`.

Per `agent-cli/docs/wiki/MAINTAINING.md`:

- **This document is an ADR.** Numbered sequentially (011), placed in `docs/wiki/decisions/`.
- **No hardcoded counts.** All counts in this doc reference where to find the truth ("see `strategies/` directory", "see `iterators/` directory").
- **`MASTER_PLAN.md` will be updated** to reference this ADR as the next phase after Phase 3 ships.
- **`build-log.md` will be updated** when each tier ships, not before (build log is for completed work).
- **Each tier completion may produce its own follow-up ADR** if a sub-decision warrants it (e.g. ADR-012 for the decision rules math in T4.1).

## Approval gate

**This ADR is in `Proposed` status.** Implementation does not begin until Chris reviews this document end-to-end and explicitly approves.

The next step after approval is to invoke the `superpowers:writing-plans` skill to break Tier 1 into a concrete implementation plan with file-level tasks, then begin T1.1 (snapshot consolidation) as the first unit of work.
