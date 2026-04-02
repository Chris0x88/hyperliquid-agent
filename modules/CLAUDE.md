# modules/ — Engine Modules

Seven core engines plus utilities. 41 files. Pure computation (zero I/O) — `_guard` classes handle persistence separately. This lets daemon iterators call engines without blocking.

## Core Engines

| Engine | Files | Purpose | Status |
|--------|-------|---------|--------|
| **APEX** | `apex_engine.py`, `apex_config.py`, `apex_state.py` | Multi-slot autonomous trading (3-5 positions) | Wired to daemon |
| **GUARD** | `guard_bridge.py`, `guard_config.py`, `guard_state.py` | Trailing stops + two-phase profit protection | Wired to daemon |
| **RADAR** | `radar_engine.py`, `radar_config.py`, `radar_state.py` | Market scanner — find setups across all HL perps | Wired to daemon |
| **PULSE** | `pulse_engine.py`, `pulse_config.py`, `pulse_state.py` | Capital inflow detector (volume + OI momentum) | Wired to daemon |
| **REFLECT** | `reflect_engine.py`, `reflect_reporter.py`, `reflect_convergence.py`, `reflect_adapter.py` | Trade outcome analysis, convergence, auto-tuning | CLI only (Phase 3) |
| **JOURNAL** | `journal_engine.py`, `journal_guard.py` | Structured trade journal, signal quality, nightly review | CLI only (Phase 3) |
| **MEMORY** | `memory_engine.py`, `memory_guard.py` | Playbook per instrument/signal, param change events | CLI only (Phase 3) |

## REFLECT Pipeline (meta-evaluation)

```
ReflectEngine.compute(trades) → ReflectMetrics
    → ConvergenceTracker.record_cycle(metrics) → is_converging?
    → ReflectAdapter.adapt(metrics, config) → [Adjustment]
    → DirectionalHysteresis.should_apply(param, direction) → bool
    → Apply adjustments → MemoryEngine.log_event("param_change")
    → Playbook.update(instrument, signal_source, outcome)
```

ReflectMetrics: win_rate, gross/net_pnl, FDR (fee drag), direction bias, holding periods, streaks, monster dependency, per-strategy breakdown, recommendations.

## Utility Modules

| Module | Purpose | Used By |
|--------|---------|---------|
| `candle_cache.py` | OHLCV SQLite cache | **v3 agent tools** (`analyze_market`), market_snapshot |
| `data_fetcher.py` | Historical data retrieval from HL | candle_cache, backtest |
| `radar_technicals.py` | EMA, RSI, ADX, ATR calculations | radar, market_snapshot |
| `trailing_stop.py` | Trailing stop price computation | guard |
| `backtest_engine.py` | Strategy backtesting harness | CLI |
| `backtest_reporter.py` | Backtest result formatting | CLI |
| `strategy_guard.py` | Strategy parameter validation | daemon |
| `judge_engine.py` | Signal quality judge | journal |
| `reconciliation.py` | Position reconciliation | daemon |
| `rotation.py` | Market rotation detection | radar |
| `smart_money/` | Smart money flow tracking | radar |
| `wallet_manager.py` | Multi-wallet coordination | daemon |

**Note:** `candle_cache.py` is now on the v3 critical path — the AI agent's `analyze_market` tool uses it for OHLCV data. Changes here affect agent tool responses.

## Upstream
- `cli/daemon/iterators/` — daemon calls engines
- `cli/commands/` — CLI commands call engines
- `cli/agent_tools.py` — v3 agent tools call candle_cache + market_snapshot

## Downstream
- `common/models.py` — data structures
- `common/thesis.py` — conviction state
- Pure computation — no exchange calls

## Testing
```bash
.venv/bin/python -m pytest tests/test_reflect_engine.py tests/test_reflect_reporter.py tests/test_reflect_convergence.py tests/test_journal_engine.py tests/test_memory_engine.py tests/test_radar_engine.py tests/test_pulse_engine.py tests/test_apex_engine.py -x -q
```
