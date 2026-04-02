# modules/ — Engine Modules

Seven core engines plus utilities. Pure computation (zero I/O) — the `_guard` classes handle persistence separately. This design lets daemon iterators call engines without blocking.

## Core Engines

| Engine | Files | Purpose | Wired? |
|--------|-------|---------|--------|
| **APEX** | `apex_engine.py`, `apex_config.py`, `apex_state.py` | Multi-slot autonomous trading (3-5 independent positions) | Via daemon |
| **GUARD** | `guard_bridge.py`, `guard_config.py`, `guard_state.py` | Trailing stops + two-phase profit protection | Via daemon |
| **RADAR** | `radar_engine.py`, `radar_config.py`, `radar_state.py` | Market scanner — find setups across all HL perps | Via daemon |
| **PULSE** | `pulse_engine.py`, `pulse_config.py`, `pulse_state.py` | Capital inflow detector (volume + OI momentum) | Via daemon |
| **REFLECT** | `reflect_engine.py`, `reflect_reporter.py`, `reflect_convergence.py`, `reflect_adapter.py` | Trade outcome analysis, convergence tracking, parameter auto-tuning | CLI only (Phase 3 wires to daemon) |
| **JOURNAL** | `journal_engine.py`, `journal_guard.py` | Structured trade journal, signal quality, nightly review | CLI only (Phase 3) |
| **MEMORY** | `memory_engine.py`, `memory_guard.py` | Playbook (what works per instrument/signal), param change events | CLI only (Phase 3) |

## REFLECT Pipeline (the meta-evaluation system)

```
ReflectEngine.compute(trades) → ReflectMetrics
    ↓
ConvergenceTracker.record_cycle(metrics) → is_converging?
    ↓
ReflectAdapter.adapt(metrics, config) → [Adjustment]
    ↓
DirectionalHysteresis.should_apply(param, direction) → bool
    ↓
Apply adjustments → MemoryEngine.log_event("param_change")
    ↓
Playbook.update(instrument, signal_source, outcome)
```

### ReflectMetrics includes:
- Core: total_trades, win_rate, gross/net_pnl, profit_factor
- Fee analysis: FDR (fee drag ratio)
- Direction: long vs short performance
- Holding period: buckets (<5m, 5-15m, 15-60m, 1-4h, 4h+)
- Streaks: max consecutive wins/losses
- Monster dependency: % of PnL from single best/worst trade
- Strategy breakdown: per-strategy performance
- Auto-generated recommendations

## Utility Modules

| Module | Purpose |
|--------|---------|
| `candle_cache.py` | OHLC data caching (SQLite) |
| `data_fetcher.py` | Historical data retrieval from HL |
| `radar_technicals.py` | EMA, RSI, ADX, ATR calculations |
| `trailing_stop.py` | Trailing stop price computation |
| `backtest_engine.py` | Strategy backtesting harness |
| `backtest_reporter.py` | Backtest result formatting |
| `strategy_guard.py` | Strategy parameter validation |
| `judge_engine.py` | Signal quality judge |
| `obsidian_reader.py` | Read from Obsidian vault |
| `obsidian_writer.py` | Write to Obsidian vault |
| `reconciliation.py` | Position reconciliation |
| `rotation.py` | Market rotation detection |
| `smart_money/` | Smart money flow tracking |
| `wallet_manager.py` | Multi-wallet coordination |

## Upstream
- `cli/daemon/iterators/` — daemon calls engines
- `cli/commands/` — CLI commands call engines

## Downstream
- `common/models.py` — data structures
- `common/thesis.py` — conviction state
- Pure computation — no exchange calls

## Current Status
- APEX, GUARD, RADAR, PULSE: Built, wired to daemon iterators
- REFLECT, JOURNAL, MEMORY: Built, accessible via CLI (`hl reflect run`), NOT wired to daemon
- Utilities: All working

## Future Direction (Phase 3)
- Wire REFLECT into daemon's AutoResearch iterator
- Wire JOURNAL into position close events
- Wire MEMORY playbook into execution decisions
- Weekly REFLECT summary to Telegram

## Testing
```bash
.venv/bin/python -m pytest tests/test_reflect_engine.py tests/test_reflect_reporter.py tests/test_reflect_convergence.py tests/test_journal_engine.py tests/test_memory_engine.py tests/test_radar_engine.py tests/test_pulse_engine.py tests/test_apex_engine.py -x -q
```
