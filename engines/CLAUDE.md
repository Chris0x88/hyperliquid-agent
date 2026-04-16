# engines/ — Shared Building Blocks

Generic, all-market engines organized by function. Pure computation — zero I/O. Daemon iterators call engines, never the reverse.

## Sub-packages

| Package | Purpose | Key Files |
|---------|---------|-----------|
| `analysis/` | Market scanning, technical signals | radar_engine, pulse_engine, apex_engine, context_engine, radar_technicals |
| `protection/` | Risk gates, trailing stops, entry validation | guard_bridge, trailing_stop, entry_critic, reconciliation, judge_engine |
| `learning/` | Self-improvement, trade review, journaling | reflect_engine, journal_engine, lesson_engine, memory_engine, lab_engine, architect_engine, backtest_engine, feedback_store, action_queue, news_engine |
| `data/` | Market data caching, classification | candle_cache, heatmap, supply_ledger, bot_classifier, data_fetcher, catalyst_bridge |

## Pattern

Each engine family follows: `engine.py` (core logic) + `config.py` (settings) + `state.py` (persistence) + `guard.py` (safety checks).

## Gotchas

- `candle_cache.py` is the critical path for AI agent tool responses
- Engines are pure computation — daemon iterators in `daemon/iterators/` call them
- All engines can be used by any market system in `trading/`
