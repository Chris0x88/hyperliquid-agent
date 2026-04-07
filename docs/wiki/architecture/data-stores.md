# Data Stores Ownership Map

Complete inventory of every persistent data store in `agent-cli`, with writers, readers, retention rules, and criticality. Generated 2026-04-07 as part of the architecture-mapping session.

## Master Table

| Store Path | Format | Owner (Writers) | Readers | Retention | Criticality | Dual-Write |
|---|---|---|---|---|---|---|
| `data/snapshots/*.json` | JSON (timestamped) | `account_collector.py:85` | `account_collector.py:282` (get_latest) | 7d full, 30d sampled | CRITICAL | Yes → memory.db |
| `data/snapshots/hwm.json` | JSON | `account_collector.py:129` | `account_collector.py:48` | Never rotates | CRITICAL | No |
| `data/memory/memory.db` | SQLite | `memory.py:162-231`, `heartbeat.py:1157-1182` | `memory.py` (queries), `heartbeat.py` | Summaries pruned >50/market | HIGH | account_snapshots table |
| `data/daemon/state.json` | JSON | `daemon/state.py:53` | `telegram_bot.py`, `cli/engine.py` | Never rotates | MEDIUM | No |
| `data/thesis/*_state.json` | JSON (per-market) | `thesis.py:149` (save) | `thesis_engine`, `execution_engine` | Manual (user updates) | CRITICAL | No |
| `data/daemon/chat_history.jsonl` | JSONL (append-only) | `telegram_agent.py:1273` (_log_chat) | `telegram_bot.py` (read for context) | Never rotates | HIGH | No |
| `data/daemon/chat_history.jsonl.bak*` | JSONL (backup) | Manual backup only | Manual recovery only | Manual | MEDIUM | Chat history backups |
| `data/daemon/journal/ticks.jsonl` | JSONL (append-only) | `journal.py:67` | `journal.py` | 7d+ (audit trail) | MEDIUM | No |
| `data/research/journal.jsonl` | JSONL (append-only) | `journal.py:29` (JOURNAL_JSONL) | `journal.py` | 7d+ | MEDIUM | No |
| `data/research/trades/*.json` | JSON (per-trade) | `journal.py:36` | `journal.py`, `reflect_engine.py` | Manual | HIGH | Trade outcome records |
| `data/cli/state.db` | SQLite | CLI commands | Status reader | Never rotates | LOW | No |
| `data/cli/trades.jsonl` | JSONL | `backtest_apex.py`, `apex_state.py` | Judge engine, reflect engine | Never rotates (manual) | MEDIUM | Backtest results |
| `data/candles/candles.db` | SQLite (WAL mode) | `candle_cache.py:110` (store_candles) | `candle_cache.py` (queries) | Never rotates (indefinite) | HIGH | No |
| `data/calendar/*.json` | JSON (static) | Manual / scheduled_check | heartbeat, scheduled_check | Never rotates | LOW | No |
| `data/config/*.json` | JSON (configs) | CLI setup, manual edit | Daemon, CLI, agent | Never auto-rotates | CRITICAL | No |
| `data/agent_memory/*.md` | Markdown | memory_write tool, consolidation | memory_read, telegram_bot | Capped at 25KB | HIGH | No |
| `data/agent_memory/MEMORY.md` | Markdown (master) | `memory_consolidator.py:441` | telegram_bot, agent_runtime | 25KB rolling trim | HIGH | Consolidated summaries |
| `data/agent_memory/dream_consolidation.md` | Markdown | `memory_consolidator.py:441` | memory_consolidator | Trimmed | MEDIUM | Dream journal |
| `data/agent_memory/x130_identity.md` | Markdown | Manual (agent identity) | agent_runtime (system prompt) | Manual | LOW | Agent personality/rules |
| `data/research/evaluations/` | JSON trees | `scheduled_check.py` | Evaluation reports | Manual cleanup | MEDIUM | Decision audit trail |
| `data/research/learnings.md` | Markdown | `memory_consolidator.py:400` | scheduled_check, agent | 25KB max | MEDIUM | Accumulated insights |
| `data/research/market_notes/` | Markdown | Manual / autoresearch | Agent reading | Manual | LOW | Market research notes |
| `data/daemon/roster.json` | JSON | `daemon/roster.py` | telegram_bot | Never rotates | LOW | Process roster |
| `data/daemon/catalyst_events.json` | JSON | `daemon/iterators/` | Risk monitoring | Never rotates | MEDIUM | Trading alerts |
| `data/daemon/telegram_commands.jsonl` | JSONL | telegram.py iterator | Replay/audit | Never rotates | LOW | Command audit trail |
| `data/daemon/telegram_last_update_id.txt` | Text | telegram.py iterator | telegram.py | Never rotates | MEDIUM | Telegram offset state |
| `data/diagnostics/*.jsonl` | JSONL (rotated) | `diagnostics.py:81` | Diagnostics reader | 5 files max, 500KB each | LOW | Audit logs |
| `state/funding.json` | JSON | `funding_tracker.py:196` | heartbeat, daemon | Never rotates (live state) | HIGH | Funding cost tracking |
| `state/telemetry.json` | JSON | `telemetry.py:177` | Status commands, monitoring | History: 20+ cycles | MEDIUM | Performance metrics |
| `data/memory/working_state.json` | JSON | `heartbeat_state.py:74` | heartbeat.py, telegram_bot.py | Never rotates (live state) | CRITICAL | Agent working state |
| `data/daemon/daemon.pid` | Text | `daemon/state.py:64` | `daemon.py` (lifecycle check) | 1 file only | MEDIUM | Process tracking |

---

## CRITICAL Stores

### 1. Account Snapshots (`data/snapshots/`)

**Files:** `YYYYMMDD_HHMMSS.json` + `hwm.json`

**Schema sample:**
```json
{
  "timestamp": 1775559240123,
  "timestamp_human": "2025-04-07 20:47:20 UTC",
  "account_value": 50000.45,
  "total_margin": 15000,
  "withdrawable": 5000,
  "spot_usdc": 1000,
  "positions_native": [...],
  "positions_xyz": [...],
  "xyz_margin_summary": {...},
  "xyz_account_value": 5000,
  "total_equity": 56000,
  "high_water_mark": 60000,
  "drawdown_pct": 6.67
}
```

**Writers**
- `cli/daemon/iterators/account_collector.py:85` — every 5 min (SNAPSHOT_INTERVAL_S=300)
- `cli/daemon/iterators/account_collector.py:129` — `_save_hwm()`

**Readers**
- `cli/daemon/iterators/account_collector.py:282` — `get_latest()`
- `telegram_bot.py` — status command
- `common/memory.py:98` — dual-write to memory.db `account_snapshots`

**Retention**
- Full: 7 days
- Sampled: days 7–30 keep 1/day
- `account_collector.py:159` `_expire_old_snapshots()` runs every tick
- >30 days: deleted

**Dual-write:** YES (best-effort to memory.db)

**Risk:** `hwm.json` never rotates; corruption loses HWM.

---

### 2. Memory DB (`data/memory/memory.db`)

SQLite (WAL). Tables: `events`, `learnings`, `observations`, `action_log`, `execution_traces`, `account_snapshots`, `summaries`. Full schema in module `common/memory.py`.

**Writers**
- `common/memory.py:164-168` — `log_event()`
- `common/memory.py:271-275` — `log_learning()`
- `cli/daemon/iterators/account_collector.py:98` — `log_account_snapshot()` (dual-write)
- `common/heartbeat.py:1157-1163` — `action_log` insert
- `common/heartbeat.py:1174-1182` — `execution_traces` insert
- `common/memory_consolidator.py:93-107` — `summaries` upsert
- `common/memory_consolidator.py:372-397` — `summaries` prune

**Readers**
- `common/memory.py:283-304` — `get_timeline()`
- `common/memory.py:306-326` — `get_learnings()`
- `common/memory.py:328-357` — `search()`
- `cli/telegram_bot.py` — memory commands
- `common/memory_consolidator.py` — consolidation reads + compresses

**Retention**
- Events / learnings / action_log / traces: indefinite
- Summaries: pruned to ≤50 per market

**Dual-write:** Partial (account_snapshots only)

---

### 3. Thesis State (`data/thesis/*_state.json`)

**Schema:**
```json
{
  "market": "xyz:BRENTOIL",
  "direction": "long",
  "conviction": 0.75,
  "thesis_summary": "...",
  "invalidation_conditions": ["..."],
  "evidence_for": [{"timestamp":..., "source":"price_action", "summary":"...", "weight":0.8, "url":"", "exit_cause":""}],
  "evidence_against": [],
  "recommended_leverage": 5.0,
  "recommended_size_pct": 0.10,
  "weekend_leverage_cap": 3.0,
  "allow_tactical_trades": true,
  "tactical_notes": "...",
  "take_profit_price": 120.5,
  "last_evaluation_ts": 1775559240000,
  "snapshot_ref": "20250407_204720.json",
  "notes": "..."
}
```

**Writers**
- `common/thesis.py:149` — `ThesisState.save()` atomic (.tmp → rename)
- `scripts/scheduled_check.py` — after AI evaluation
- `cli/mcp_server.py:668` — after API call

**Readers**
- `common/thesis.py:157-187` `load()`, `:190-199` `load_all()`
- `cli/daemon/iterators/thesis_engine.py` — every tick
- `execution_engine.py` — for sizing
- `telegram_bot.py` — `/thesis`

**Staleness modifiers (in code)**
- <7d: full conviction
- 7–14d: linear taper conviction → 0.3
- >14d: clamped 0.3

**Risk:** No dual-write. `/thesis` Telegram edits are UI-only and require `scheduled_check` to persist.

---

### 4. Working State (`data/memory/working_state.json`)

Live agent state — escalation level, positions, ATR cache, last_prices, last_add_ms, conviction snapshots.

**Writers**
- `common/heartbeat_state.py:74` — `save_working_state()` atomic
- `common/heartbeat.py:1188` — after every heartbeat
- `cli/agent_runtime.py:406` — after `scheduled_check`

**Readers**
- `common/heartbeat_state.py:56` — `load_working_state()` on startup
- `common/heartbeat.py` — every tick
- `cli/telegram_bot.py` — `/status`, `/health`

**Retention:** overwrites each tick; daily session_peak reset.

**Risk:** No WAL recovery; corruption loses escalation state.

---

## HIGH Priority Stores

### 5. Chat History (`data/daemon/chat_history.jsonl`)
- Writer: `cli/telegram_agent.py:1273` `_log_chat()`
- Readers: `agent_runtime.py:406` (consolidation), `telegram_bot.py` (memory hints)
- **No rotation logic.** Current size: ~78 KB (verified 2026-04-07; the prior "6 MB"
  figure was wrong). Growth is slow at current chat volume — not an immediate concern,
  but rotation logic should be added before this file is allowed to grow into the
  hundreds of MB.
- Backups `.bak`, `.bak2` are manual.

### 6. Candle Cache (`data/candles/candles.db`)
SQLite WAL. Tables `candles` (PK coin/interval/timestamp_ms) and `fetch_log`.
- Writer: `modules/candle_cache.py:110` `store_candles()` (INSERT OR IGNORE)
- Readers: `:115-130` `get_candles()`, `:144-150` `date_range()`
- **No cleanup. Indefinite growth.** Regenerable from exchange API.

### 7. Funding Tracker (`state/funding.json`)
Per-symbol cumulative paid/received funding.
- Writer: `common/funding_tracker.py:196` `_save()` after each `record()`
- Readers: `:201-218` `_load()`, `:164-169` `summary()`
- **No rotation.** History irrecoverable if lost.

---

## MEDIUM Priority Stores

### 8. Telemetry (`state/telemetry.json`)
- Writer: `common/telemetry.py:177` `end_cycle()` — keeps last ~20 cycles in `history`
- Readers: `/health`, `/status`

### 9. Daemon State (`data/daemon/state.json`)
`{tier, tick_count, daily_pnl, total_pnl, total_trades}`
- Writer: `cli/daemon/state.py:53`
- Reader: `:55-58` on startup, `telegram_bot.py`

### 10. Journals (`data/daemon/journal/ticks.jsonl`, `data/research/journal.jsonl`)
- Writer: `cli/daemon/iterators/journal.py:67` (tick snapshots), `:200+` (trade entries)
- **No rotation. Unbounded.**

### 11. Diagnostics (`data/diagnostics/*.jsonl`)
- Writer: `common/diagnostics.py:81`
- **Properly rotated:** 500 KB max/file, 5 files max.

---

## LOW Priority Stores

### 12. Agent Memory (`data/agent_memory/*.md`)
- `MEMORY.md`, `dream_consolidation.md`, `x130_identity.md`, `learnings.md` (symlink)
- Writers: `common/memory_consolidator.py:441-444` `_trim_learnings_file()`, `common/tools.py:481-489` `memory_write()` tool
- Readers: `agent_runtime.py:406` (consolidation), `telegram_bot.py` `/memory`, system prompt injection
- 25 KB rolling trim

### 13. Configs (`data/config/*.json`)
`watchlist.json`, `market_config.json`, `escalation_config.json`, `profit_rules.json`, `model_config.json`.
- Writer: `common/watchlist.py:140` `write_watchlist()`; manual edits
- Readers: daemon startup
- **No backup mechanism. CRITICAL impact if lost.**

---

## Orphans, Risks, Gaps

**No retention policy (current size on 2026-04-07 in parens):**

1. 🔴 **ACTIVE concern** — `data/daemon/journal/ticks.jsonl` (~1.1 MB after one day,
   ~365 MB/year unrotated). Highest priority for adding rotation logic.
2. 🟡 LATENT — `data/daemon/chat_history.jsonl` (~78 KB; growth slow, but unbounded)
3. 🟡 LATENT — `data/candles/candles.db` (~800 KB SQLite; growing slowly,
   regenerable from exchange API if lost)
4. ✅ NON-ISSUE — `data/research/journal.jsonl` (~1.6 KB; basically empty —
   verify the writer is firing as intended)
5. ✅ MITIGATED — `data/research/learnings.md` (~25 KB; already at the
   `_trim_learnings_file()` cap, trim logic working)

**Original "5 unbounded orphans" framing was overstated** — only `ticks.jsonl` is an
active growth concern. See `verification-ledger.md` for the verification trail.

**No dual-write backup (single point of failure):**
1. Thesis states
2. Working state
3. Funding tracker

**Unclear ownership:**
1. `data/daemon/daemon.pid` — `daemon/state.py:64` writes; cleanup-on-shutdown unverified
2. `data/daemon/telegram_last_update_id.txt` — format undocumented
3. `data/research/evaluations/` — written by `scheduled_check.py`; no documented cleanup

**Implicit dependencies:**
1. Thesis → memory.db (Evidence objects)
2. Working state → account snapshots availability
3. Journal → position tracking accuracy

---

## Writer / Reader Line Map

### memory.db Writers
```
common/memory.py:162-168                          log_event()
common/memory.py:271-275                          log_learning()
cli/daemon/iterators/account_collector.py:98     log_account_snapshot()  [dual-write]
common/heartbeat.py:1157-1163                     action_log INSERT
common/heartbeat.py:1174-1182                     execution_traces INSERT
common/memory_consolidator.py:93-107              summaries UPSERT
common/memory_consolidator.py:372-397             summaries PRUNE
```

### Snapshots Writers
```
cli/daemon/iterators/account_collector.py:85       write JSON
cli/daemon/iterators/account_collector.py:129      save HWM
cli/daemon/iterators/account_collector.py:246-266  _expire_old_snapshots()
```

### Thesis Writers
```
common/thesis.py:149                ThesisState.save()
scripts/scheduled_check.py          after AI evaluation
cli/mcp_server.py:668               after API call
```

### Chat History Writer
```
cli/telegram_agent.py:1273          _log_chat()
```

### Candles Writer
```
modules/candle_cache.py:110         store_candles()
```

### Working State Writer
```
common/heartbeat_state.py:74        save_working_state()
common/heartbeat.py:1188            (calls save_working_state())
```

---

## Recommendations

1. **Rotate `chat_history.jsonl`** — keep last N lines, archive older.
2. **Daily-rotate `ticks.jsonl`** — one file per day with TTL.
3. **Document thesis ownership** — single canonical writer path.
4. **Backup mechanism for thesis + working state** — periodic snapshot to memory.db.
5. **Codify retention policy** — make implicit rules explicit in code, not docs.
6. **Verify `daemon.pid` cleanup** on graceful shutdown.
