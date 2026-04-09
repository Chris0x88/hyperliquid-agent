# Timer & Loop Audit — 2026-04-09

**Phase:** C of SYSTEM_REVIEW_HARDENING_PLAN.md
**Scope:** every loop, timer, and scheduled job that touches the trading system.
**Emphasis per user:** *"track and check timer and loops for when processes run,
how they run, sequencing, is it common sense... processes that interweave and
not just waterfall code structure alone."*
**Status:** findings only. No code changes in this phase. Fixes queue into Phase D
(`COHESION_HARDENING_LIST.md`).

---

## 1. Execution model summary

The system has **three independent processes** running concurrently under launchd,
each with its own loop cadence, plus **two additional out-of-process writers** that
can touch the same on-disk state.

### 1.1 Processes under launchd

| Label | Entry point | Cadence | KeepAlive |
|-------|-------------|---------|-----------|
| `com.hyperliquid.daemon`    | `.venv/bin/python -m cli.main daemon start --tier watch --mainnet --tick 120` | continuous loop, 120 s tick | `KeepAlive=true` |
| `com.hyperliquid.telegram`  | `.venv/bin/python -m cli.telegram_bot` | continuous polling (separate process; command handlers fire on user input) | `KeepAlive=true` |
| `com.hyperliquid.heartbeat` | `.venv/bin/python scripts/run_heartbeat.py` | **launchd-driven 120 s `StartInterval` one-shot** — launchd respawns the script every 120 s | `KeepAlive=false` |

These three launchd jobs share a single filesystem tree under
`/Users/cdi/Developer/HyperLiquid_Bot/agent-cli/data/` and a single SQLite database
at `data/memory/memory.db`. **There is no lock coordination between the three
processes.** They rely on atomic-rename discipline, SQLite's own lock, and
append-only semantics for JSONL files to stay consistent.

### 1.2 Daemon internal tick model

`cli/daemon/clock.py` implements a Hummingbot-style tick loop. Per tick (120 s):

1. Rebuild the active iterator set from `cli/daemon/tiers.py` for the current tier
   (WATCH / REBALANCE / OPPORTUNISTIC).
2. Run each iterator's `tick(ctx)` in **list order** through a
   `run_with_middleware` wrapper enforcing a 10 s per-iterator timeout.
3. Drain `ctx.order_queue` to the adapter via `_execute_orders` (applies risk gate
   + per-asset authority check).
4. Persist state, run health-window error budget check, possibly auto-downgrade
   tier.
5. `time.sleep(tick_interval)` and repeat.

**Most iterators implement their own internal throttle** on top of the global tick:
they stash `_last_poll_mono` (or `_last_run`, `_last_check`, `_last_tick`) in
process memory and return early when their own interval has not elapsed. This
means an iterator's effective cadence is `max(daemon_tick_s,
iterator_interval_s)`, and the throttle state is **lost on every daemon restart**.

### 1.3 Production tier

`/Users/cdi/Developer/HyperLiquid_Bot/agent-cli/data/config/oil_botpattern.json`
ships with `enabled: true` and `decisions_only: true` (shadow mode); the daemon
runs in `--tier watch`. The iterator registrations in WATCH (see §2) are the
set actually live today.

### 1.4 Out-of-process writers to shared state

Beyond the daemon process, the following writers touch files the daemon reads:

- **telegram_bot.py (main process)** — `/activate` writes `data/config/oil_botpattern.json`; `/selftuneapprove` and `/selftunereject` rewrite `data/strategy/oil_botpattern_proposals.jsonl`; `/patternpromote` rewrites `data/research/bot_pattern_candidates.jsonl`; `/disrupt` appends to `data/supply/disruptions.jsonl`; AI agent runtime writes `data/thesis/*.json`.
- **heartbeat (launchd one-shot)** — `common/heartbeat.py` calls `proxy.place_trigger_order()` to place SLs directly on the exchange and writes `data/memory/memory.db` via `common/heartbeat_state.py`. This is a direct writer to the database that `memory_backup` snapshots.

The rest of the document treats these writers as first-class actors in the
interweaving graph.

---

## 2. Iterator inventory with cadences and dependencies

All paths relative to `/Users/cdi/Developer/HyperLiquid_Bot/agent-cli/`.

| Iterator | Source | Throttle / cadence | Reads | Writes | Depends on | Depended on by | Tiers | Kill switch | Failure mode |
|---|---|---|---|---|---|---|---|---|---|
| `account_collector` | `cli/daemon/iterators/account_collector.py` | 300 s (`SNAPSHOT_INTERVAL_S`) internal; still injects `ctx.high_water_mark` every tick | HL adapter `get_account_state()` + `get_xyz_state()`; `data/snapshots/hwm.json`; `ctx.prices` | `data/snapshots/YYYYMMDD_HHMMSS.json`; `data/snapshots/hwm.json`; `ctx.snapshot_ref`, `ctx.high_water_mark`, `ctx.account_drawdown_pct`; dual-writes `log_account_snapshot()` → `memory.db` | HL adapter; `connector` for `ctx.prices` (same-tick) | every iterator that reads `ctx.high_water_mark` / drawdown (`risk`, `execution_engine`, `oil_botpattern` drawdown brakes) | W/R/O | none (hard-coded always-on) | HWM lost if snapshot write fails (fallback to in-memory); best-effort dual-write to memory.db; exception path drops ctx fields (downstream sees 0) |
| `connector` | `cli/daemon/iterators/connector.py` | every tick | HL adapter `get_account_state`, `get_snapshot`, `get_xyz_state`, `get_positions`, `get_all_markets`, `get_candles` | `ctx.balances`, `ctx.prices`, `ctx.positions`, `ctx.total_equity`, `ctx.candles`, `ctx.all_markets` | HL adapter | literally every downstream iterator | W/R/O | none | **Hard-fail path**: clock aborts the tick if `connector` fails (see `clock.py:144`) |
| `liquidation_monitor` | `cli/daemon/iterators/liquidation_monitor.py` | every tick (internal state for alert-repeat throttling only) | `ctx.positions`, `ctx.prices` | `ctx.alerts` | `connector` | `telegram` (alert drain) | W/R/O | none (hard-coded) | Per-position iteration; a bad position is caught inline; empty `ctx.positions` → silent |
| `funding_tracker` | `cli/daemon/iterators/funding_tracker.py` | 300 s internal (`check_interval_s`) | `ctx.positions`, `ctx.prices`, HL adapter `get_snapshot.funding_rate`; `data/daemon/funding_tracker.jsonl` (load on start) | `data/daemon/funding_tracker.jsonl`; `ctx.alerts` | `connector`, HL adapter | `oil_botpattern` reads `_load_funding_by_instrument` (file); `autoresearch` reads the jsonl | W/R/O | none | Best-effort JSONL append; rate fetch failures silently drop that instrument |
| `protection_audit` | `cli/daemon/iterators/protection_audit.py` | 120 s internal (`CHECK_INTERVAL_S`) | `common.heartbeat._fetch_open_trigger_orders()` for both native + xyz; `ctx.positions`, `ctx.prices` | `ctx.alerts` | `connector`; the heartbeat process (for trigger-order state on the exchange) | `telegram` | W/R/O | Import failure or wallet-resolve failure → silent skip; per-position exceptions bubble |
| `brent_rollover_monitor` | `cli/daemon/iterators/brent_rollover_monitor.py` | 3600 s internal (`CHECK_INTERVAL_S`) | `data/calendar/brent_rollover.json` with mtime reload; falls back to built-in `DEFAULT_CALENDAR` | `ctx.alerts` | — | `telegram` | W/R/O | Missing/corrupt calendar → empty state; `_fired` set is process-memory only (resets on restart) |
| `market_structure` | `cli/daemon/iterators/market_structure_iter.py` | 300 s internal (`RECOMPUTE_INTERVAL_S`) | `common.watchlist.get_watchlist_coins()`, `ctx.positions`, `ctx.thesis_states`, `ctx.prices`, `ctx.candles`; `modules/candle_cache.py` SQLite cache; **direct HL `/info` POST every 300 s** to refresh candle cache (1h/4h/1d for all markets, 1m for BRENTOIL/CL) | `ctx.market_snapshots`, `ctx.prices` (for missing watchlist coins); writes candles into `CandleCache` (SQLite) | `connector`, HL `/info` endpoint | `thesis_engine`, `execution_engine`, `oil_botpattern`, `bot_classifier` (reads `CandleCache`) | W/R/O | Per-market exceptions logged and skipped; cache open failure disables cache path but still computes from ctx.candles |
| `thesis_engine` | `cli/daemon/iterators/thesis_engine.py` | 60 s internal (`RELOAD_INTERVAL_S`) | `data/thesis/*.json` via `common.thesis.ThesisState.load_all()` | `ctx.thesis_states`, `ctx.alerts` | AI agent runtime (thesis files written out-of-process) | `execution_engine`, `oil_botpattern`, `autoresearch`, `journal`, `lesson_author` | W/R/O | Load failure falls through with empty `ctx.thesis_states` → downstream conservative defaults |
| `radar` | `cli/daemon/iterators/radar.py` | 300 s internal (`DEFAULT_SCAN_INTERVAL`) | `ctx.all_markets`, `ctx.candles["BTC"]` | `data/research/signals.jsonl`; `ctx.radar_opportunities`; `ctx.alerts` | `connector` | `apex_advisor` | W/O (not R) | Engine-init or scan exception → silent skip |
| `news_ingest` | `cli/daemon/iterators/news_ingest.py` | per-feed `poll_interval_s` (default 60 s) via `self._last_poll[name]` | `data/config/news_ingest.json`; `data/config/news_feeds.yaml`; `data/config/news_rules.yaml`; **live HTTP GET to every configured RSS/iCal feed URL**; `data/news/headlines.jsonl` (seen IDs) | `data/news/headlines.jsonl`, `data/news/catalysts.jsonl`, `data/daemon/external_catalyst_events.json` (via `catalyst_bridge`); `ctx.alerts` | external RSS/iCal feeds (real internet) | `supply_ledger`, `bot_classifier`, `catalyst_deleverage`, `lesson_author`, `entry_critic` | W/R/O | Per-feed HTTP/parse exception skips that feed; config reload every tick (no mtime gate) |
| `supply_ledger` | `cli/daemon/iterators/supply_ledger.py` | mtime-watch on `catalysts.jsonl` + 300 s `recompute_interval_s` | `data/config/supply_ledger.json`; `data/news/catalysts.jsonl` (mtime-gated); `data/supply/disruptions.jsonl` (dedupe) | `data/supply/disruptions.jsonl` (append); `data/supply/state.json` (atomic rewrite); `ctx.alerts` | `news_ingest`, telegram `/disrupt` (out-of-process writer) | `bot_classifier`, `oil_botpattern` (reads `data/supply/state.json`) | W/R/O | `auto_extract` disabled → read-only path; broken jsonl line is logged and skipped |
| `heatmap` | `cli/daemon/iterators/heatmap.py` | `poll_interval_s` (default 60 s) internal | `data/config/heatmap.json`; **HL `/info` POST** for `l2Book` + `metaAndAssetCtxs` per configured instrument | `data/heatmap/zones.jsonl` (append); `data/heatmap/cascades.jsonl` (append); `ctx.alerts` | HL `/info` endpoint | `bot_classifier`, `entry_critic`, `oil_botpattern` | W/R/O | Per-instrument exception logged; long-gap OI state reset (`window_s > cfg_window*3`); no bounded retention on zones.jsonl |
| `bot_classifier` | `cli/daemon/iterators/bot_classifier.py` | `poll_interval_s` (default 300 s) internal | `data/config/bot_classifier.json`; `data/news/catalysts.jsonl` (24 h window); `data/supply/state.json`; `data/heatmap/cascades.jsonl` (4 h window); **direct HL `/info` POST for 1 m candles** (no cache read-through; the `_default_candles_provider` fetches live per poll); `modules/candle_cache.py` as fallback | `data/research/bot_patterns.jsonl` (append); `ctx.alerts` | `news_ingest`, `supply_ledger`, `heatmap`, direct HL API | `oil_botpattern` (reads `bot_patterns.jsonl`); `oil_botpattern_patternlib` | W/R/O | HTTP fetch failure → cache fallback → returns empty and skips instrument |
| `oil_botpattern` | `cli/daemon/iterators/oil_botpattern.py` | `tick_interval_s` (default 60 s) internal | `data/config/oil_botpattern.json`; `data/research/bot_patterns.jsonl`; `data/news/catalysts.jsonl`; `data/supply/state.json`; `data/thesis/*.json`; `data/research/journal.jsonl` (recent closed oil_botpattern); `data/daemon/funding_tracker.jsonl`; `ctx.positions`, `ctx.prices`, `ctx.total_equity`; `data/strategy/oil_botpattern_state.json` | `data/strategy/oil_botpattern_state.json` (atomic); `data/strategy/oil_botpattern_journal.jsonl` (append); `data/research/journal.jsonl` (append on close); `data/strategy/adapt_log.jsonl` (adaptive evaluator); `ctx.order_queue` (only when `decisions_only: false`); `ctx.alerts` | `market_structure`, `thesis_engine`, `news_ingest`, `supply_ledger`, `heatmap`, `bot_classifier`, `funding_tracker`, `risk` | `exchange_protection` (1 tick lag on new positions); `journal`, `lesson_author` (via `journal.jsonl`); `oil_botpattern_tune`, `oil_botpattern_reflect`, `oil_botpattern_shadow` (read its journals) | W/R/O | Per-instrument exception logged; state file atomic; **decisions_only shadow mode in prod** |
| `oil_botpattern_tune` (L1) | `cli/daemon/iterators/oil_botpattern_tune.py` | `tick_interval_s` (default 300 s) internal | `data/config/oil_botpattern_tune.json`; `data/config/oil_botpattern.json` (current strategy cfg); `data/research/journal.jsonl` (closed oil_botpattern); `data/strategy/oil_botpattern_journal.jsonl` (decisions); `data/strategy/oil_botpattern_tune_audit.jsonl` | **`data/config/oil_botpattern.json` (atomic rewrite)**; `data/strategy/oil_botpattern_tune_audit.jsonl` (append); `ctx.alerts` | `oil_botpattern` (reads its journals; writes the config it reads) | **`oil_botpattern` reads the same config it writes** | W (per uncommitted `tiers.py` change) / R / O | Kill switch OFF at ship; audit-append failure does NOT roll back config mutation (intentional) |
| `oil_botpattern_reflect` (L2) | `cli/daemon/iterators/oil_botpattern_reflect.py` | wall-clock 7 d via `_is_run_due` on `state.last_run_at` (persisted) | `data/config/oil_botpattern_reflect.json`; `data/strategy/oil_botpattern_reflect_state.json`; `data/research/journal.jsonl`; `data/strategy/oil_botpattern_journal.jsonl` | `data/strategy/oil_botpattern_reflect_state.json` (atomic); `data/strategy/oil_botpattern_proposals.jsonl` (append); `ctx.alerts` | oil_botpattern's journals | `oil_botpattern_shadow` (shadow-eval of approved proposals); telegram `/selftuneproposals`, `/selftuneapprove` | W (per uncommitted `tiers.py`) / R / O | Kill switch OFF; state seeded on first run so `_is_run_due` is deterministic across restarts |
| `oil_botpattern_patternlib` (L3) | `cli/daemon/iterators/oil_botpattern_patternlib.py` | `tick_interval_s` (default 600 s) internal | `data/config/oil_botpattern_patternlib.json`; `data/research/bot_patterns.jsonl`; `data/research/bot_pattern_catalog.json`; `data/research/bot_pattern_candidates.jsonl`; `data/strategy/oil_botpattern_patternlib_state.json` | `data/research/bot_pattern_candidates.jsonl` (append); state file (atomic); `ctx.alerts` | `bot_classifier` (via `bot_patterns.jsonl`) | telegram `/patterncatalog`, `/patternpromote` | W/R/O (all tiers) | Kill switch OFF; read-only wrt classifier behavior |
| `oil_botpattern_shadow` (L4) | `cli/daemon/iterators/oil_botpattern_shadow.py` | `tick_interval_s` (default 3600 s) internal | `data/config/oil_botpattern_shadow.json`; `data/strategy/oil_botpattern_proposals.jsonl`; `data/research/journal.jsonl`; `data/strategy/oil_botpattern_journal.jsonl` | **`data/strategy/oil_botpattern_proposals.jsonl` (atomic rewrite)** — stamps `shadow_eval` field; `data/strategy/oil_botpattern_shadow_evals.jsonl` (append); `ctx.alerts` | `oil_botpattern_reflect` (proposals emitted); telegram (approvals mark status=approved) | telegram `/shadoweval` | W (per uncommitted `tiers.py`) / R / O | Per-proposal exception logged; proposals rewrite is atomic but racy with telegram `/selftuneapprove` — see §5.2 |
| `pulse` | `cli/daemon/iterators/pulse.py` | 120 s internal (`DEFAULT_SCAN_INTERVAL`) | `ctx.all_markets`, `ctx.candles`; internal `_scan_history` | `data/research/signals.jsonl` (append); `ctx.pulse_signals`; `ctx.alerts` | `connector` | `apex_advisor` | W/O (not R) | Engine init or scan exception silently skipped; empty `ctx.all_markets` → no-op |
| `liquidity` | `cli/daemon/iterators/liquidity.py` | every tick (pure time-of-day compute) | system clock | `ctx.alerts` with `data["regime"]` dict | — | Any iterator that reads the regime tag off `ctx.alerts` data (currently informational only) | W/R/O | Stateless regime detection; no failure mode beyond the pure function |
| `risk` | `cli/daemon/iterators/risk.py` | every tick | `ctx.prices`, `ctx.positions`, `ctx.high_water_mark`, `ctx.account_drawdown_pct`; `parent/risk_manager.py` state | `ctx.risk_gate`, `ctx.alerts` | `account_collector` (HWM + drawdown), `connector` | **Every write path**: `execution_engine`, `guard`, `oil_botpattern`, `_execute_orders` in clock | W/R/O | Risk state in process memory; no persistence → resets on restart |
| `guard` | `cli/daemon/iterators/guard.py` | every tick | `ctx.positions`, `ctx.prices`; `data/guard/` state store (SQLite) | `data/guard/` state; `ctx.order_queue` (close intents); exchange SL sync via adapter; `ctx.alerts` | `connector`, HL adapter | execution engine + exchange SL ownership | R/O only | Adapter failure degrades to log-only; authority-reclaimed path tears down bridge |
| `rebalancer` | `cli/daemon/iterators/rebalancer.py` | per-slot `slot.tick_interval` (strategy-defined), gated by `slot.last_tick` | `ctx.active_strategies`, `ctx.prices`, `ctx.positions` | `ctx.order_queue` | `connector` | `_execute_orders` | R/O | Strategy exception caught per slot and alerted |
| `execution_engine` | `cli/daemon/iterators/execution_engine.py` | `REBALANCE_INTERVAL_S = 120 s` internal | `ctx.thesis_states`, `ctx.positions`, `ctx.prices`, `ctx.balances`, `ctx.account_drawdown_pct` | `ctx.order_queue`, `ctx.alerts` | `market_structure`, `thesis_engine`, `account_collector`, `risk` | `exchange_protection` (1 tick lag), `journal`, `clock._execute_orders` | R/O | Conservative defaults when thesis missing; drawdown halts at 25 %, ruin-close at 40 % |
| `exchange_protection` | `cli/daemon/iterators/exchange_protection.py` | 60 s internal (`TICK_INTERVAL_S`) | `ctx.positions`, HL adapter (trigger orders) | Exchange SL placements/cancels; `ctx.alerts` | `execution_engine` (positions); `connector` | — (end of chain; SL lives on exchange) | R/O | Adapter exceptions logged; no-op without adapter |
| `profit_lock` | `cli/daemon/iterators/profit_lock.py` | 300 s internal (`check_interval`) | `ctx.positions`, `ctx.prices`, `ctx.balances`; `data/daemon/profit_locks.jsonl` | `data/daemon/profit_locks.jsonl` (append); `ctx.order_queue` (reduce-only partials); `ctx.alerts` | `connector` | `_execute_orders`, `journal` | R/O | Reads USDC balance directly (not total_equity) — stale if spot moves |
| `catalyst_deleverage` | `cli/daemon/iterators/catalyst_deleverage.py` | 3600 s internal (`check_interval`), mtime-watch on `data/daemon/external_catalyst_events.json` | `data/daemon/catalyst_events.json`, `data/daemon/external_catalyst_events.json`, `ctx.positions` | `data/daemon/catalyst_events.json`; `ctx.order_queue`, `ctx.alerts` | `news_ingest` (via `external_catalyst_events.json` bridge) | `_execute_orders` | R/O | Past-event window no-op; corrupt file logged and skipped |
| `apex_advisor` | `cli/daemon/iterators/apex_advisor.py` | 60 s internal (`ADVISE_INTERVAL_S`) | `ctx.pulse_signals`, `ctx.radar_opportunities`, `ctx.positions`, `ctx.prices` | `ctx.alerts` (dry-run proposals only; never queues orders) | `pulse`, `radar` | `telegram` | W/O (not R) | Import/init failure disables; advisor is observer-only |
| `autoresearch` | `cli/daemon/iterators/autoresearch.py` | 1800 s internal (`EVAL_INTERVAL_S`) | `ctx.thesis_states`, `ctx.positions`, `ctx.prices`, `ctx.balances`; `data/daemon/journal.jsonl`, `data/daemon/funding_tracker.jsonl`, `data/daemon/catalyst_events.json`, `data/research/journal.jsonl` | `data/research/evaluations/*.json`; `data/research/learnings.md` (append); `ctx.alerts` (none — writes are side effects for the agent to read) | `journal`, `funding_tracker`, `catalyst_deleverage`, `thesis_engine` | AI agent runtime reads `learnings.md` | W/R/O | Per-subroutine exception logged; ReflectEngine wrapped in try/except |
| `memory_consolidation` | `cli/daemon/iterators/memory_consolidation.py` | 3600 s internal (`_CONSOLIDATION_INTERVAL`) | `data/memory/memory.db` via `common.memory_consolidator.consolidate()` | **`data/memory/memory.db`** (compresses old events → summaries, prunes) | memory.db writers (all of them) | All downstream reads of memory.db | W/R/O | Consolidation exception logged; DB lock contention not explicitly handled |
| `journal` | `cli/daemon/iterators/journal.py` | every tick (change-detection); UTC-daily prune | `ctx.positions`, `ctx.prices`, `ctx.thesis_states`, `ctx.risk_gate`; previous-tick `_prev_positions` | `data/daemon/journal/ticks-YYYYMMDD.jsonl` (every tick); `data/research/trades/NNN-*.json`; `data/research/journal.jsonl` (on close); `ctx.alerts` (on close) | `connector`, `thesis_engine` | `lesson_author`, `oil_botpattern_tune/reflect/shadow` (all read `journal.jsonl`); `autoresearch` (REFLECT) | W/R/O | Exit-price 4-step resolution cascade refuses to write garbage rows |
| `lesson_author` | `cli/daemon/iterators/lesson_author.py` | every tick (byte-offset cursor on `journal.jsonl`) | `data/config/lesson_author.json`; `data/research/journal.jsonl` (seek from cursor); `data/thesis_backup/*_state.json`; `data/research/learnings.md`; `data/news/catalysts.jsonl`; `data/daemon/lesson_author_state.json` | `data/daemon/lesson_candidates/<entry_id>.json` (atomic); `data/daemon/lesson_author_state.json` | `journal`, `thesis_engine` (via backup), `news_ingest`, `autoresearch` | AI agent `/lessonauthorai` command (reads candidates) | W/R/O | Per-row exception skipped; truncation detection resets offset; refuse-to-write-garbage rule |
| `entry_critic` | `cli/daemon/iterators/entry_critic.py` | every tick (position-fingerprint dedup) | `ctx.positions`; `data/heatmap/zones.jsonl`, `cascades.jsonl`; `data/news/catalysts.jsonl`; `data/research/bot_patterns.jsonl`; `data/daemon/entry_critic_state.json` | `data/research/entry_critiques.jsonl` (append); state file (atomic); `ctx.alerts` | `account_collector` (positions via connector), `heatmap`, `news_ingest`, `bot_classifier` | telegram `/critique` | W/R/O | Per-entry exception logged; bounded fingerprint set (1000 max) |
| `memory_backup` | `cli/daemon/iterators/memory_backup.py` | `interval_hours` (default 1 h) internal | `data/memory/memory.db` (SQLite online-backup, ro) | `data/memory/backups/memory-*.db`; daily + weekly promoted slots | **All writers to `memory.db`**: `memory_consolidation`, `lesson_author` (FTS5 lessons table), heartbeat (`heartbeat_state`), `account_collector` dual-write, AI agent runtime, telegram_bot command path | `action_queue` reads newest backup mtime | W/R/O | `integrity_check` failure keeps snapshot but does NOT rotate; online-backup is lock-safe; restore drill unexercised |
| `action_queue` | `cli/daemon/iterators/action_queue.py` | `interval_hours` (default 24 h) internal | `data/research/action_queue.jsonl`; `data/memory/memory.db` (pending-lesson count); `data/memory/backups/` (newest mtime) | `data/research/action_queue.jsonl` (atomic via `ActionQueue.save`); `ctx.alerts` | `memory_backup`, `lesson_author` (indirectly via pending count) | telegram `/nudge` | W/R/O | 24 h wall-clock gated on `_last_run` (monotonic; resets on restart); corrupt state falls back to fresh queue |
| `telegram` | `cli/daemon/iterators/telegram.py` | every tick (2 s rate limiter on actual send) | `ctx.alerts`, `ctx.order_queue`, `ctx.risk_gate`, `ctx.active_strategies`, `ctx.total_equity`; env vars + Keychain + `data/daemon/telegram.json` | Telegram API HTTP POSTs | **All other iterators** (they write to `ctx.alerts`) | end of chain (external Telegram) | W/R/O | Markdown-fallback-to-plain on parse error; HTTP exception logged; 2 s internal rate limiter |

**Iterator count:** 33 iterators total across `cli/daemon/iterators/` (excluding `__init__.py`, `__pycache__`, and the private `_format.py` helper).

---

## 3. Sequencing analysis

The order of iterators **within a tier list in `tiers.py`** is the execution order
(`clock.py:_rebuild_active_set` preserves registration order filtered by tier
set). Rules checked below are verbatim from the review plan §6.2.

### 3.1 Proper ordering verified

- `account_collector` first → **verified** (line 6 WATCH, 43 REBALANCE, 78 OPPORTUNISTIC).
- `connector` second → **verified** (line 7 / 44 / 79).
- `market_structure` before `thesis_engine` → **verified** (WATCH: lines 12 → 13; REBALANCE: 48 → 49; OPPORTUNISTIC: 83 → 84).
- `thesis_engine` before `execution_engine` → **verified** (REBALANCE: 49 → 50; OPPORTUNISTIC: 84 → 85).
- `oil_botpattern` AFTER `news_ingest`, `supply_ledger`, `heatmap`, `bot_classifier` → **verified** (WATCH: 15/16/17/18 → 19; REBALANCE: 56/57/58/59 → 60; OPPORTUNISTIC: 92/93/94/95 → 96).
- `exchange_protection` AFTER `execution_engine` → **verified** (REBALANCE: 50 → 51; OPPORTUNISTIC: 85 → 86).
- `journal` after `execution_engine` → **verified** (REBALANCE: 50 → 70; OPPORTUNISTIC: 85 → 107).
- `lesson_author` after `journal` → **verified** (REBALANCE: 70 → 71; OPPORTUNISTIC: 107 → 108).
- `entry_critic` after `execution_engine` → **verified** (REBALANCE: 50 → 72; OPPORTUNISTIC: 85 → 109).
- `telegram` LAST → **verified** (WATCH: line 40; REBALANCE: 75; OPPORTUNISTIC: 112).

### 3.2 Order violations found

**V1. `oil_botpattern_tune` runs in the SAME tick after `oil_botpattern`, and its writes to `data/config/oil_botpattern.json` are seen by oil_botpattern on the NEXT tick.** (REBALANCE: 60 → 61; OPPORTUNISTIC: 96 → 97.) Given tune's own 300 s throttle this isn't a same-tick conflict in the nominal case, but there is zero guarantee: if daemon tick drifts longer than the tune throttle, oil_botpattern can read config state, tune can rewrite config later in the same tick, and the next tick's oil_botpattern re-reads. Window is bounded but there is no happens-before contract documented anywhere. **Severity: low-medium** — tune currently kill-switched off.

**V2. `pulse` / `apex_advisor` ordering across tiers is inconsistent.** In WATCH (lines 28 / 31), `pulse` runs AFTER `apex_advisor` (line 31) — but `apex_advisor` reads `ctx.pulse_signals` from `pulse`. In REBALANCE the order is different: `pulse` is NOT in the tier list at all, but `apex_advisor` is also not there. In OPPORTUNISTIC (lines 101 / no apex), `pulse` is present but `apex_advisor` is NOT registered. So the only place apex_advisor runs is WATCH, and in WATCH the order is:
  - line 28: `pulse`
  - line 31: `apex_advisor`

Re-reading: pulse comes BEFORE apex_advisor. So pulse fills `ctx.pulse_signals` first, then apex_advisor reads. **Not a violation** — noted as "initially looked wrong but verified correct."

**V3. `radar` only appears in WATCH (line 14) and OPPORTUNISTIC (line 91), not in REBALANCE.** `apex_advisor` reads `ctx.radar_opportunities`. In REBALANCE, apex_advisor is not registered, so this is consistent. But in OPPORTUNISTIC, `apex_advisor` is also not registered — meaning radar's output goes nowhere in that tier. Dead scan. **Severity: low** — wasted compute cycles on an unused channel.

**V4. `catalyst_deleverage` runs after `news_ingest` → `supply_ledger` but before `journal`.** In REBALANCE line 67 (after news_ingest on 56, supply_ledger on 57). catalyst_deleverage watches `data/daemon/external_catalyst_events.json` via mtime, which is written by `news_ingest` on the same tick. Catalyst bridge writes are inside the news_ingest `persist()` call; catalyst_deleverage then picks them up via `_load_external_catalysts_from_file` with mtime check. **This works only because the mtime check is the coordination primitive.** If two `news_ingest` ticks fire between two `catalyst_deleverage` ticks, the deleverager still only sees the last state — fine. But if `news_ingest` fires while `catalyst_deleverage` is mid-iteration reading the file, there's a narrow window. **Severity: low** — Python's GIL serializes the actual read/write, and json.load is atomic at the Python level, but the file itself is NOT written atomically by `catalyst_bridge.persist` (needs verification in Phase D).

**V5. In WATCH, `market_structure` runs at line 12 BEFORE `news_ingest`, but `bot_classifier` at line 18 reads candles through its OWN direct HL POST (not via market_structure).** Not a sequencing violation, but a **data-path duplication**: market_structure fetches 1 m candles for BRENTOIL/CL every 300 s into the cache, and bot_classifier independently fetches the same 1 m candles every 300 s from the API (see `_default_candles_provider`). Two processes hitting the same endpoint for the same data. **Severity: low** — wasted network, not incorrect.

---

## 4. Cadence analysis

### 4.1 Too fast

- **`thesis_engine` at 60 s** — thesis files are user/AI-written and valid for months per `feedback_thesis_longevity.md`. Reading them every 60 s is fine mechanically, but re-emits the stale-thesis review-reminder alert every 60 s worth of log line. The alert-dedup is via the telegram iterator's `_sent_alerts` cooldown, not at the source. Net cost: 6× the necessary file reads per 6-minute window. **Recommendation**: bump to 300 s or mtime-watch.
- **`news_ingest` at 60 s per feed** — RSS feeds update on minutes-to-hours cadences, not seconds. Polling every 60 s is aggressive and risks IP bans on some providers. Per-feed override exists but defaults are tight.
- **`connector` every tick (120 s)** — fine for balances and positions, but it also calls `get_all_markets()` which is a broad HL meta query used only by `radar` and `pulse`, which throttle at 300 s and 120 s respectively. `all_markets` is recomputed at 120 s for consumers that don't need it that often.
- **`lesson_author` and `entry_critic` every tick** — both have internal dedup (byte-offset cursor / fingerprint set) so no-op when nothing changed, but they still do file-exist checks and (for entry_critic) path builds every single tick. Fine mechanically; excessive in log noise.

### 4.2 Too slow

- **`memory_backup` at 1 h with NO backup-on-restart trigger.** The monotonic `_last_run = 0` check fires on first tick after restart, so it actually DOES fire promptly — but only if the daemon has been running for longer than the tick interval. If the daemon restarts every 5 minutes in a crash loop, memory_backup fires each restart (unintended rapid backup). If it restarts every 30 minutes it fires every 30 minutes until stable. **Behavior is correct but surprising.**
- **`action_queue` at 24 h with monotonic `_last_run` that resets every restart.** Daemon restarts daily (e.g., launchd respawn on crash, manual restart during a deploy) mean the 24 h nudge never fires if restarts happen more often than 24 h. **This is a real concern** because the launchd plist has `KeepAlive=true` and the daemon has crashed in the past.
- **`oil_botpattern_reflect` at 7 d wall-clock IS persisted** (the `state.last_run_at` is written to `data/strategy/oil_botpattern_reflect_state.json`), so it survives restarts. **Correct.** But when first enabled, it runs on the first tick because `state.last_run_at` is `None`, which is the documented behavior.
- **`funding_tracker` at 300 s** — HL funding is hourly so 5-minute poll is 12× per hour, which is over-sampling. The tracker math compensates (hourly rate × elapsed seconds) but the extra writes to `funding_tracker.jsonl` are noise.
- **`autoresearch` at 1800 s (30 min)** — the docstring says "compressed from daily for faster improvement loops" but reflects over a 7-day window. If the window doesn't change between runs, every 30-minute eval mostly re-writes the same data to `learnings.md`. Append-only file is growing linearly with no pruning.

### 4.3 Fine as-is

- `account_collector` at 300 s — matches the scheduled task cadence that consumes `get_latest()`.
- `radar` at 300 s, `pulse` at 120 s, `apex_advisor` at 60 s — cascade is properly ordered so apex sees fresh inputs.
- `heatmap` at 60 s — L2 book legitimately moves fast enough to justify minute-level polling for cascade detection.
- `bot_classifier` at 300 s — 5-minute rhythm matches the 1 m candle window lookback (60 minutes) and is slow enough to not thrash the API.
- `oil_botpattern` at 60 s — strategy tick needs to react on the minute; matches heatmap cadence.
- `market_structure` at 300 s — 1h/4h/1d indicators barely move in 5 minutes.
- `brent_rollover_monitor` at 3600 s — roll dates don't move inside an hour.
- `protection_audit` at 120 s — matches the heartbeat launchd cadence it's verifying.
- `exchange_protection` at 60 s — matches the risk-manager ruin-floor cadence.
- `memory_consolidation` at 3600 s — matches memory_backup so the DB is quiescent when backed up (but see §5.2).
- `catalyst_deleverage` at 3600 s — event granularity is days, hourly check is plenty.
- `oil_botpattern_patternlib` at 600 s — observational; 10-minute cadence is generous.
- `oil_botpattern_shadow` at 3600 s — counterfactual replay is compute-heavy; hourly is fine.
- `oil_botpattern_tune` at 300 s — shadows the strategy's minute tick and only acts on closed trades, which are rare.

---

## 5. Time-loop interweaving (the core of this audit)

This is the section the user explicitly asked for. Per-iterator cadence is a
one-dimensional view; the interesting pathologies live in the cross-iterator
data chains and parallel-writer overlaps.

### 5.1 Cross-iterator write→read chains

These are the concrete A-writes-file-X, B-reads-file-X links I found by
cross-referencing every iterator's `Reads` and `Writes` columns in §2.

**Chain C1: Catalyst-to-decision latency (news → strategy).**
```
news_ingest (60 s poll)
  → data/news/catalysts.jsonl (append)
  → supply_ledger (mtime-gated + 300 s recompute)
  → data/supply/state.json (atomic rewrite)
  → bot_classifier (300 s poll)
  → data/research/bot_patterns.jsonl (append)
  → oil_botpattern (60 s poll)
  → OrderIntent (in shadow, decisions_only=true today)
```
**Worst-case A→B latency:** 60 s (news) + 300 s (supply) + 300 s (classifier) + 60 s (strategy) = **720 s / 12 minutes** from RSS fetch to strategy reaction. In practice more, because `supply_ledger` re-decomputes every 300 s *on its own internal clock*, which is phase-offset from the news_ingest clock. **Collision window:** two adjacent iterators can read stale intermediate state if the upstream write completes between the consumer's last read and the consumer's current read. Since all the intermediate files are append-only JSONL or atomic-rewrite JSON, the consumer always sees a consistent snapshot — but may see yesterday's snapshot if it ticks first. **Invariant:** the pipeline is eventually consistent with 12-minute worst-case lag; there is no end-to-end bound. **Risk:** a fresh catalyst sitting in `catalysts.jsonl` for 12 minutes before the strategy sees it defeats the purpose of a shock-reactive oil strategy.

**Chain C2: Thesis file write→read race (AI agent vs thesis_engine).**
```
AI agent runtime (telegram_bot process, triggered by user or /thesis command)
  → data/thesis/<market>.json  (write_text non-atomic in most paths)
  → thesis_engine (60 s poll, in daemon process)
  → ctx.thesis_states
  → execution_engine + oil_botpattern (same tick)
```
**Collision window:** if the AI agent writes the thesis file mid-tick while thesis_engine's `ThesisState.load_all()` is iterating the directory, a half-written file is read and json.loads raises. The iterator catches the exception silently (line 63-66) and continues with stale state. **Invariant:** NONE. There is no atomic rename on thesis writes in most write paths (would need to verify `common/thesis.py` write side — out of scope for this phase). **Severity: medium** — thesis rewrites are rare (weekly by AI) so the collision window is narrow, but a silently-dropped thesis update that the execution engine then sizes against is a real risk.

**Chain C3: Self-tune vs strategy config race (oil_botpattern_tune → oil_botpattern).**
```
oil_botpattern (reads data/config/oil_botpattern.json every 60 s via _reload_config)
  ↕
oil_botpattern_tune (atomic rewrite of the SAME file every 300 s)
  ↕
telegram_bot /activate command (atomic rewrite of the SAME file, user-driven)
```
**Three separate writers of `data/config/oil_botpattern.json`:** oil_botpattern_tune (daemon process), telegram_bot /activate (telegram process), manual hand-edit by the user. oil_botpattern reads the file on every tick. All three writers use atomic-rename (verified for tune and activate; hand-edit depends on editor). **Invariant:** atomic-rename guarantees any single reader sees either the pre-write or post-write state, never a torn write — **provided the reader uses `json.loads(path.read_text())` which is exactly what `_reload_config` does**. Good. **But:** there is NO write-serialization between the two daemon-owned writers (tune and the telegram /activate process). If tune reads the config, computes a proposal, and writes back while /activate reads the SAME config and writes back, one of them clobbers the other's change. Tune's audit log will still have the tune's nudge recorded, but the config on disk will only reflect whichever writer's rename was later. **Severity: medium** — both writers are currently kill-switched-off in practice (tune by config, /activate as a one-off operator action), but when both are live this is a real silent-overwrite bug.

**Chain C4: Journal-to-lesson-to-learnings chain.**
```
oil_botpattern + guard + execution_engine
  → ctx.order_queue → clock._execute_orders → exchange fill
  → next tick: ctx.positions no longer contains the closed position
  → journal._detect_position_changes → data/research/journal.jsonl (append)
  → SAME tick: lesson_author._read_new_lines (byte-offset cursor) → data/daemon/lesson_candidates/<id>.json (atomic)
  → autoresearch (1800 s) → data/research/learnings.md (append)
  → AI agent reads learnings.md next session
```
**Latency:** 0 → 30 minutes depending on where in the autoresearch cycle the close lands. **Interweaving risk:** `lesson_author` runs every tick and consumes its cursor AT THE SAME TICK `journal` appends. If `lesson_author` runs BEFORE `journal` within the same tick (see tiers.py: journal at line 70, lesson_author at line 71 — lesson_author IS after, good) then the cursor catches the new row. **Verified in tiers.py:** lesson_author is consistently after journal. **Invariant:** OK.

**Chain C5: memory.db write collisions.**
```
Process A: common.memory_consolidator.consolidate()  — daemon 3600 s cadence
Process B: memory_backup iterator — daemon 3600 s cadence
Process C: lesson_author log_lesson — AI agent path, any time
Process D: account_collector log_account_snapshot dual-write — daemon 300 s cadence
Process E: heartbeat heartbeat_state — launchd 120 s cadence (separate process)
Process F: AI agent runtime writes (telegram_bot process) — ad-hoc
```
**Six writers of a single SQLite file, three separate processes.** SQLite's lock model allows ONE writer at a time; readers can coexist with the single writer via WAL. Process-level races are handled by SQLite's file lock. **But:** `memory_backup` uses `sqlite3.Connection.backup()` with `mode=ro` source connection — this is documented to be safe against concurrent writers. **Invariant:** OK for correctness. **Cadence collision:** `memory_consolidation` and `memory_backup` both fire every 3600 s in the same process, with independent `_last_run` monotonic clocks. If the daemon starts and both clocks happen to align, `memory_consolidation` runs first (registered earlier — line 33 WATCH, line 69 REBALANCE) and then `memory_backup` runs after (line 38 WATCH, line 73 REBALANCE). This ordering means the backup captures the post-consolidation state, which is desirable. **But:** `memory_consolidation` is NOT in OPPORTUNISTIC tier list? Actually re-reading the file — yes, REBALANCE line 69 and OPPORTUNISTIC line 106 both have it. Fine. **Net finding: OK,** but worth documenting the ordering as a deliberate invariant in `cli/daemon/CLAUDE.md`.

**Chain C6: Heatmap zones → entry_critic read.**
```
heatmap (60 s poll)
  → data/heatmap/zones.jsonl (APPEND-ONLY, never pruned)
  → entry_critic (every tick, reads zones.jsonl at position time)
```
**zones.jsonl is append-only with zero retention.** Every heatmap tick adds new zone snapshots. Over 30 days at 60s cadence = 43,200 snapshots × N zones each. entry_critic reads the file by iterating lines. **Implication:** entry_critic's read cost grows linearly with daemon uptime. No collision, just a slow leak. **Severity: low-medium** — will manifest as tick-time regression after a few weeks of uptime.

**Chain C7: Proposals rewrite race (oil_botpattern_shadow vs /selftuneapprove).**
```
oil_botpattern_shadow (daemon, 3600 s) rewrites data/strategy/oil_botpattern_proposals.jsonl atomically, stamping shadow_eval on approved proposals
  ↕
telegram_bot /selftuneapprove + /selftunereject commands (telegram process) rewrite the SAME file to flip status to "approved"/"rejected"
```
**Two separate processes doing atomic rewrites on the same file.** Atomic-rename gives last-writer-wins semantics. If a user approves proposal #5 in telegram at the SAME moment shadow is rewriting the file to stamp proposal #4's eval, one of them loses. Which one depends on which process calls `os.replace` last. **Severity: low today** (shadow kill-switched off, no proposals), but on promotion this is a silent data-loss path.

### 5.2 Parallel-writer safety

The following files have **more than one writer**, across process boundaries
where relevant.

| File | Writers | Atomic? | Collision behavior | Invariant |
|------|---------|---------|--------------------|-----------|
| `data/config/oil_botpattern.json` | `oil_botpattern_tune` (daemon), `/activate` (telegram), manual edit | **All atomic-rename** | last-writer-wins silently | no write-serialization between daemon and telegram; risk is bounded by both being kill-switched today |
| `data/strategy/oil_botpattern_proposals.jsonl` | `oil_botpattern_reflect` (append), `oil_botpattern_shadow` (atomic rewrite), telegram `/selftuneapprove` / `/selftunereject` (atomic rewrite) | **Rewrites atomic, appends not atomic-across-processes** | append race on reflect; rewrite race between shadow and telegram | no lock; risk is today bounded by kill switches |
| `data/memory/memory.db` | `memory_consolidation`, `memory_backup` (ro), `lesson_author` FTS5, `account_collector` dual-write, heartbeat (heartbeat_state), AI agent runtime, telegram bot commands | SQLite file lock | **Single-writer serialized by SQLite**; backup is explicitly safe | correctness-safe, but no explicit contract around which process is authoritative for which table |
| `data/news/catalysts.jsonl` | `news_ingest` (append) | Append-only | single writer | OK |
| `data/heatmap/zones.jsonl` | `heatmap` (append) | Append-only | single writer, no retention | OK for correctness, grows unbounded |
| `data/heatmap/cascades.jsonl` | `heatmap` (append) | Append-only | single writer, no retention | OK for correctness, grows unbounded |
| `data/research/journal.jsonl` | `journal` (append), `oil_botpattern` (append on close) | Append-only | two writers in SAME daemon process (sequential within a tick) | safe inside-process |
| `data/supply/disruptions.jsonl` | `supply_ledger` (append via `append_disruption`), telegram `/disrupt` (append) | Append-only | two writers in DIFFERENT processes | POSIX append is atomic up to PIPE_BUF; jsonl rows are well under that → **OK** |
| `data/supply/state.json` | `supply_ledger` (atomic rewrite only) | Atomic | single writer | OK |
| `data/research/bot_pattern_candidates.jsonl` | `oil_botpattern_patternlib` (append), telegram `/patternpromote` / `/patternreject` (atomic rewrite) | Mixed | **rewrite clobbers in-flight append** | risk bounded by kill switches + rare user action |
| `data/thesis/*.json` | AI agent runtime (telegram process) | **Most write paths are not atomic** (needs verification in Phase D) | thesis_engine read collides with half-written file → silent stale state | depends on `common/thesis.py` write side |
| `data/config/news_ingest.json` etc. | operator hand-edit only | n/a | single writer | OK |

### 5.3 Phase-drift cases

Several iterators at near-but-not-equal cadences will drift relative to each
other over time:

- **`account_collector` (300 s) vs `funding_tracker` (300 s)** — both 300 s, both monotonic — stay in phase with each other by coincidence of having the same interval.
- **`market_structure` (300 s) vs `radar` (300 s)** — same story, co-phased by coincidence.
- **`pulse` (120 s) vs `apex_advisor` (60 s)** — apex_advisor is 2× as frequent. Every second apex tick sees the same pulse_signals as the first. Apex dedups via `_last_proposal[key]` so this is benign but wastes a cycle.
- **`heatmap` (60 s) vs `oil_botpattern` (60 s)** — co-phased within a tick; strategy reads heatmap output from same-tick writes. OK because tiers.py runs heatmap before oil_botpattern in every tier.
- **`news_ingest` per-feed (default 60 s) vs `supply_ledger` (300 s mtime-watch + 300 s recompute)** — supply_ledger fires 1 in 5 news_ingest ticks on average, but its mtime-watch fires on every supply_ledger tick if catalysts.jsonl was touched. Phase drift means the catalyst→state latency varies between ~60 s and ~360 s randomly.
- **`memory_consolidation` (3600 s) vs `memory_backup` (3600 s)** — both 1 h. Consolidation registered first so it runs first. **IF the daemon restarts**, both `_last_run` clocks reset to 0, both fire on first eligible tick, and consolidation wins the race. Stable invariant.
- **`oil_botpattern` (60 s) vs `oil_botpattern_tune` (300 s)** — strategy is 5× as frequent. Every 5th strategy tick sees a potentially-new config. Between tune-writes, strategy uses stale config. Bounded 300 s drift.

**No phase-drift case currently introduces a correctness bug.** The interesting
one to watch is news → supply → classifier → strategy (C1 above) where the
drift compounds across four hops.

### 5.4 Long-window cadences (weekly, monthly)

Three long-window iterators, each with a different persistence story:

**`oil_botpattern_reflect` — 7-day wall clock.**
State persisted to `data/strategy/oil_botpattern_reflect_state.json` via atomic
rewrite. `_is_run_due` reads last_run_at from the state file, so a daemon
restart does NOT reset the 7-day window. **Verified safe.** First-run seeds the
state with `last_run_at=None` which `_is_run_due` treats as "run now," so the
first weekly scan fires promptly after enabling.

**`action_queue` — 24-hour wall clock.**
State persisted to `data/research/action_queue.jsonl` for ITEM last-done/nudged
timestamps, but the ITERATOR's `_last_run` is `time.monotonic()` which **resets
to 0 on every daemon restart**. Meaning: if the daemon restarts more often than
24 h, the iterator fires every restart (same behavior as memory_backup). Each
fire calls `evaluate()` which uses the PERSISTED per-item nudge cooldown, so
items aren't re-nudged on every restart, but the daemon still does the work of
scanning the queue. **Net: correctness-safe, performance-surprising.** If the
daemon never runs for 24 continuous hours, the 24 h cadence is moot — items
only advance via the per-item timestamps.

**`oil_botpattern` drawdown windows — daily/weekly/monthly.**
State persisted inside `data/strategy/oil_botpattern_state.json` with explicit
`maybe_reset_*_window` calls. Window resets are wall-clock based, not monotonic.
**Correct across restarts.**

**One real concern in this section:** `autoresearch` runs a 7-day rolling
reflection every 30 minutes and APPENDS to `data/research/learnings.md`. Over
7 days at 30 minutes that's 336 append cycles, each re-processing the SAME
7 days of journal data and writing the SAME reflection. `learnings.md` grows
~250 KB per week for no new information after the first run.

---

## 6. Edge cases

### 6.1 Daemon restart behavior per iterator

The daemon restarts via launchd `KeepAlive=true` on any crash or manual restart.
Each iterator handles restart differently:

| Iterator | State reload on restart? | Behavior |
|---|---|---|
| `account_collector` | Yes — HWM from `hwm.json` | Correct |
| `connector` | No state | Stateless — correct |
| `liquidation_monitor` | No — `_last_tier` in memory | Re-alerts every critical position once on restart (arguably correct — "system just came back, tell me where I stand") |
| `funding_tracker` | Yes — from `funding_tracker.jsonl` | Reloads per-instrument cumulative |
| `protection_audit` | No — `_last_state` in memory | Re-alerts every CRITICAL stop state on restart (same as liq monitor) |
| `brent_rollover_monitor` | No — `_fired` set in memory | **Re-fires every tier alert on restart.** If contract is within 3 days, user gets the "in 3 days" warning every time the daemon restarts. Nuisance, not bug. |
| `market_structure` | No — snapshots in memory | First tick is a full recompute — correct |
| `thesis_engine` | Reads files fresh | Correct |
| `radar` / `pulse` / `apex_advisor` | No state persisted | First tick is a full scan — correct |
| `news_ingest` | Seen-ID set from headlines.jsonl on first tick | **Does NOT dedup across restart by default** (only in-memory `_alerted_catalyst_ids`) — re-alerts catalyst X if the daemon restarts after alerting it. |
| `supply_ledger` | Seen-catalyst-id set in memory; disruptions.jsonl on disk | Re-processes all catalysts_jsonl on first tick because `_catalysts_mtime` is reset to 0 |
| `heatmap` | `_prev_state` in memory; zones/cascades on disk | First tick after restart cannot compute OI delta — drops one cascade detection cycle |
| `bot_classifier` | No state persisted | Correct — heuristics are stateless |
| `oil_botpattern` | Yes — full state from `oil_botpattern_state.json` | **Correct** including drawdown windows and `_last_conflict_at` (in-memory, will be empty on restart — gives a fresh grace period, which is favorable) |
| `oil_botpattern_tune` | No — `_last_poll_mono` in memory | Fires on first tick, then every 300 s — **could nudge twice within rate-limit window if restart happens between nudges** (rate limit is checked via `audit_index` so it's safe, but the attempt still happens) |
| `oil_botpattern_reflect` | Yes — `state.last_run_at` persisted | Correct |
| `oil_botpattern_patternlib` | Yes — state persisted | Correct |
| `oil_botpattern_shadow` | No — `_last_poll_mono` in memory | Fires on first tick (same pattern) |
| `liquidity` | No — stateless | Correct |
| `risk` | No — in-process RiskManager state | **Re-starts with safe_mode=false regardless of pre-crash state.** If the system was in COOLDOWN pre-crash, restart clears it. **Severity: MEDIUM** — a crash-loop during a risk gate event silently clears the gate. |
| `guard` | Yes — `GuardState` from `data/guard/` | Correct |
| `rebalancer` | Per-slot `last_tick` in-memory `Slot` state (persisted via roster) | Correct if roster persistence works |
| `execution_engine` | No state persisted | `_last_rebalance` reset — correct (re-rebalances on next tick) |
| `exchange_protection` | No — `_tracked` in memory | Must re-fetch exchange trigger orders to re-populate; currently the `on_start` does not do this. **Severity: MEDIUM** — on restart, exchange_protection forgets which SLs it placed and may place duplicates on next interval. |
| `profit_lock` | `_locked_total` reloaded from jsonl; `_session_locked` resets | Correct for cumulative; session count is by design |
| `catalyst_deleverage` | Yes — from `catalyst_events.json` | Correct |
| `autoresearch` | No — session_start reset | First run after restart re-processes the 7-day window — correct (idempotent but wasteful per §5.4) |
| `memory_consolidation` | No — `_last_run` monotonic | Fires on first tick, then hourly |
| `journal` | No — `_prev_positions` in memory | **First tick after restart treats all current positions as NEW, so any positions closed DURING the restart are missed.** Severity: MEDIUM — post-restart, if you opened at T-1 and closed at T (while daemon was down), the close is silently lost. |
| `lesson_author` | Yes — byte-offset cursor persisted | Correct — resumes where it left off |
| `entry_critic` | Yes — fingerprint set persisted (capped at 1000) | Correct |
| `memory_backup` | No — `_last_run` monotonic | Fires on first tick after restart, regardless of when last backup ran. Desirable — always get a fresh snapshot after a crash. |
| `action_queue` | Partial — per-item timestamps in JSONL; iterator `_last_run` monotonic | See §5.4 |
| `telegram` | No — dedup set in memory | Re-sends alerts within their cooldown window on restart (expected) |

### 6.2 Tier downgrade cleanup

When `clock._maybe_downgrade_tier` flips from OPPORTUNISTIC → REBALANCE → WATCH,
iterators that WERE in the downgraded set are simply dropped from the active
list on the NEXT `_rebuild_active_set` call. Their `.tick(ctx)` stops being
called. **There is no `on_tier_exit` callback.** Consequences:

- `execution_engine`: stops placing new orders immediately. Existing positions still have SLs (from exchange_protection in REBALANCE+, or from heartbeat in WATCH). **OK**.
- `exchange_protection`: when the tier drops from REBALANCE to WATCH, exchange_protection stops ticking, but the SL orders it placed on the exchange REMAIN. The next protection_audit tick in WATCH notices the SL and does NOT alert. **OK**, but the ownership handoff to heartbeat is implicit and undocumented.
- `guard`: when downgraded out, active guard bridges are abandoned in-process. The next tier-up re-creates bridges from `data/guard/` state store. **OK**.
- `catalyst_deleverage`: only runs in REBALANCE/OPPORTUNISTIC. On downgrade, pending catalysts are abandoned until tier upgrades. **POTENTIAL BUG**: if the daemon downgrades to WATCH during an approaching catalyst, the deleverage never fires.
- `oil_botpattern` family (5, tune, reflect, shadow): WATCH tier now includes all of these per the uncommitted `tiers.py` change. **No downgrade gap** in the new config.
- `profit_lock`: REBALANCE+ only. Downgrades abandon partial close logic — existing positions just stop getting profits locked. **Acceptable**.

**No iterator currently leaks resources on tier downgrade** (no open HTTP sockets, no DB connections held across ticks). The gap is correctness: catalyst_deleverage silently goes inert.

### 6.3 Kill switch hot-reload

Every iterator with a kill switch (`data/config/<name>.json → enabled`) reloads
the file via its `_reload_config` method on every tick. There is no mtime-cache
gate — the JSON is re-parsed per tick. **Kill switch hot-reload is verified
working for all configured iterators.** Flipping `enabled: false` takes effect
on the next tick within 120 s.

**Exception: `oil_botpattern.short_legs_enabled`.** This sub-flag is read every
tick inside the gate chain, so it's also hot-reloadable. **But** the daemon does
NOT re-initialize any position state when it flips. If you flip
`short_legs_enabled: true` while a long position is open, the next tick starts
allowing shorts immediately — which is the desired behavior. If you flip it
back to `false` while a short is open, the iterator continues managing the
open short (it's `_manage_existing` path doesn't gate on the flag; only new
shorts are blocked). **Arguably correct**, but worth documenting.

### 6.4 Out-of-process writers (AI commands, Telegram handlers)

Already covered in §5.2. Summary of WHICH out-of-process flows touch files the
daemon reads:

1. **Telegram bot command handlers** (cli/telegram_bot.py, cli/telegram_commands/*):
   - `/activate` → rewrites `data/config/oil_botpattern.json`
   - `/selftuneapprove` / `/selftunereject` → rewrites `data/strategy/oil_botpattern_proposals.jsonl`
   - `/patternpromote` / `/patternreject` → rewrites `data/research/bot_pattern_candidates.jsonl`; updates `data/research/bot_pattern_catalog.json`
   - `/disrupt` → appends to `data/supply/disruptions.jsonl`
   - `/thesis` paths → write `data/thesis/*.json`
2. **AI agent runtime** (inside telegram_bot process):
   - Thesis state writes on AI-generated analyses
   - `/lessonauthorai` reads `data/daemon/lesson_candidates/` and persists to `memory.db` lessons table
   - Agent memory writes in `data/agent_memory/`
3. **Heartbeat script** (separate launchd process, 120 s one-shots):
   - Places exchange trigger orders via `proxy.place_trigger_order` — state stays on the exchange, no local file touched except `data/memory/memory.db` via `heartbeat_state` module
4. **User manual edits** — any `data/config/*.json` file, any `data/thesis/*.json` file

**Every one of these paths is currently coordinated only by atomic-rename +
SQLite locking.** There is no explicit lock protocol, no write-ordering
contract, no file lock across processes. The current system works because
(a) most of the out-of-process writes are rare (user-driven Telegram commands),
(b) SQLite handles its own write serialization, and (c) append-only JSONL
tolerates concurrent appends up to PIPE_BUF (4 KB on macOS — well above a
jsonl row). **The risk surface grows when kill switches flip on** because
daemon-owned writers start touching the same files more frequently.

---

## 7. External schedulers

| Source | What it runs | Cadence | Restart policy | Log paths |
|---|---|---|---|---|
| `launchd com.hyperliquid.daemon` | `.venv/bin/python -m cli.main daemon start --tier watch --mainnet --tick 120` | continuous loop, 120 s internal tick | `KeepAlive=true`, `RunAtLoad=false` | `data/daemon/daemon_launchd.log`, `data/daemon/daemon_launchd_err.log` |
| `launchd com.hyperliquid.telegram` | `.venv/bin/python -m cli.telegram_bot` | continuous poll loop (Telegram long-poll) | `KeepAlive=true`, `RunAtLoad=false` | `data/daemon/telegram_bot.log`, `data/daemon/telegram_bot_err.log` |
| `launchd com.hyperliquid.heartbeat` | `.venv/bin/python scripts/run_heartbeat.py` | `StartInterval=120` — launchd respawns every 120 s | `KeepAlive=false`, `RunAtLoad=false` | `data/memory/logs/heartbeat_launchd.log`, `data/memory/logs/heartbeat_launchd_err.log` |
| `crontab -l` (user) | `/Users/cdi/Developer/pacman/scripts/archive_chat_history.sh` | `0 9-21 * * *` (hourly 9 AM–9 PM) | cron default | managed by pacman, unrelated to HL bot |
| In-process timers | **None.** No `schedule.`, `APScheduler`, `threading.Timer`, or `asyncio.sleep`-based loops in `cli/` per the `Grep` pass. All cadence lives in the clock tick + iterator internal throttles. | n/a | n/a | n/a |

**launchd liveness verified** via `launchctl list | grep -i hyper` during this
audit: all three are running (`com.hyperliquid.daemon` PID 18320,
`com.hyperliquid.telegram` PID 72197, `com.hyperliquid.heartbeat` respawning
per interval).

**No in-process Python schedulers outside the daemon clock.** This is a
strength — cadence is all visible from `tiers.py` + the per-iterator config
JSONs.

**Heartbeat one-shot pattern** is worth calling out: every 120 s launchd fires
`run_heartbeat.py`, which places SL trigger orders on the exchange. This
process runs **in parallel with the daemon process on the SAME 120 s cadence**.
There is no coordination between the two. The daemon's `exchange_protection`
iterator runs in REBALANCE+/OPPORTUNISTIC only; in WATCH (current tier), the
heartbeat script is the SOLE placer of exchange SLs. The daemon's
`protection_audit` iterator reads the SL state the heartbeat placed. This
write-read chain crosses a process boundary with ZERO lock — it relies on
HL's own API serializing trigger order placements. **This is a deliberate
architectural choice** per CLAUDE.md's "single-instance pacman kill" pattern,
and the protection_audit doc-string explicitly names it
"Coordination model: heartbeat = SL placer / protection_audit = SL verifier."
**Cross-process correctness relies on the exchange as the source of truth
for trigger orders.** OK.

---

## 8. Recommendations (prioritized for Phase D)

Scoring: Impact (1 low – 3 capital-risking) × Likelihood (1 rare – 3 inevitable) − Effort (1 <1 h – 3 multi-session) = Priority. Items ≥5 are Phase D P0.

| # | Title | Impact | Likelihood | Effort | Priority | Source |
|---|-------|--------|-----------|--------|----------|--------|
| R1 | **Catalyst-to-strategy pipeline latency unbounded (12+ min worst case)** — document the end-to-end invariant and add a phase-coupled fast-path for severity≥5 catalysts (bypass the bot_classifier hop and push directly into `oil_botpattern`'s next tick) | 3 | 2 | 2 | **5 (P0)** | §5.1 C1 |
| R2 | **`journal` misses trades closed during daemon downtime** — on `on_start`, reconcile `ctx.positions` with the last persisted position set and emit a synthetic close event for any missing instruments | 3 | 2 | 2 | **5 (P0)** | §6.1 journal row |
| R3 | **`risk` iterator loses gate state across restart** — persist `RiskManager.state` to `data/daemon/risk_state.json` on save and reload in `on_start` | 3 | 2 | 1 | **6 (P0)** | §6.1 risk row |
| R4 | **`exchange_protection._tracked` lost on restart → potential duplicate SLs** — on `on_start`, fetch current exchange trigger orders and repopulate `_tracked` before first tick | 3 | 2 | 2 | **5 (P0)** | §6.1 exchange_protection row |
| R5 | **Triple-writer race on `data/config/oil_botpattern.json`** — add a file-lock guard around `_write_strategy_config_atomic` (lightweight `fcntl.lockf` on a sidecar `.lock` file) so the daemon and telegram process serialize writes | 3 | 1 | 2 | 2 (P1) | §5.2 oil_botpattern config row |
| R6 | **`thesis_engine` silently drops half-written thesis files** — audit `common/thesis.py` write paths, enforce atomic-rename on all of them; in the iterator, on JSONDecodeError, retry once 100 ms later before falling through | 3 | 2 | 2 | **5 (P0)** | §5.1 C2 |
| R7 | **`action_queue` never fires if daemon restarts more often than 24 h** — replace monotonic `_last_run` with a persisted `last_sweep_ts` in the state JSONL, so the 24 h cadence is wall-clock | 2 | 2 | 1 | 3 (P1) | §5.4 |
| R8 | **`zones.jsonl` and `cascades.jsonl` grow unbounded** — add an hour-retention rotation in the heatmap iterator (same pattern `journal.py` uses for `ticks-YYYYMMDD.jsonl`) | 2 | 3 | 2 | 4 (P1) | §5.1 C6 |
| R9 | **`news_ingest` re-alerts same catalyst after restart** — persist `_alerted_catalyst_ids` to a state file like `entry_critic` does | 1 | 3 | 1 | 3 (P1) | §6.1 news_ingest row |
| R10 | **`brent_rollover_monitor._fired` set lost on restart** — persist to a state file, same as R9 | 1 | 3 | 1 | 3 (P1) | §6.1 brent row |
| R11 | **`market_structure` and `bot_classifier` double-fetch 1 m candles for BRENTOIL/CL** — have bot_classifier read from `CandleCache` first; fall through to direct HL only if cache is cold | 1 | 3 | 1 | 3 (P1) | §3.2 V5 |
| R12 | **`autoresearch` at 30 min writes `learnings.md` appends with mostly-unchanged output** — gate on actual content change (hash the reflection dict, skip append if unchanged) | 1 | 3 | 1 | 3 (P1) | §4.2 autoresearch row |
| R13 | **`oil_botpattern_proposals.jsonl` rewrite race (shadow vs telegram)** — add a file-lock guard (same primitive as R5) | 2 | 1 | 2 | 1 (P2) | §5.1 C7 |
| R14 | **`thesis_engine` poll at 60 s is excessive vs multi-month thesis validity** — switch to mtime-watch or bump to 300 s | 1 | 2 | 1 | 2 (P2) | §4.1 thesis row |
| R15 | **`catalyst_deleverage` goes inert in WATCH tier on tier-downgrade during an approaching event** — either register it in WATCH (read-only warning mode) or add an on-startup alert if a pending catalyst is within 24 h when not in an active tier | 3 | 1 | 2 | 2 (P2) | §6.2 catalyst_deleverage row |
| R16 | **Document the `memory_consolidation` → `memory_backup` ordering invariant in `cli/daemon/CLAUDE.md`** so future edits to `tiers.py` don't silently reverse it | 1 | 2 | 1 | 2 (P2) | §5.1 C5 |
| R17 | **Document the `oil_botpattern_tune` → `oil_botpattern` config write-read order as a deliberate invariant** and add a test that fails if someone reorders `tiers.py` | 2 | 1 | 2 | 1 (P2) | §3.2 V1 |
| R18 | **`radar` is dead in OPPORTUNISTIC because `apex_advisor` is WATCH-only** — either add apex_advisor to OPPORTUNISTIC (reads same ctx fields) or remove radar from OPPORTUNISTIC | 1 | 3 | 1 | 3 (P1) | §3.2 V3 |

**P0 summary:** R1 (catalyst latency), R2 (missed closes on restart), R3 (risk gate reset on restart), R4 (exchange_protection forgets SLs on restart), R6 (thesis-file race).

All five P0s share a pattern: **they are failures that manifest only after a
process restart or across process boundaries.** The daemon's happy-path
behavior within a stable uptime window is mostly correct; the interweaving
pathologies are clustered at the boundaries.
