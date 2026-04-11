# modules/ — Engine Modules

Core engines plus utilities. Pure computation (zero I/O) — `_guard` classes handle persistence separately.

## Core Engines

| Engine | Key File | Purpose | Status |
|--------|----------|---------|--------|
| APEX | `apex_engine.py` | Multi-slot autonomous trading | Wired via `cli/daemon/iterators/apex_advisor.py` (dry-run, WATCH tier only) |
| GUARD | `guard_bridge.py` | Trailing stops + profit protection | Wired to daemon |
| RADAR | `radar_engine.py` | Market scanner — find setups | Wired to daemon |
| PULSE | `pulse_engine.py` | Capital inflow detector | Wired to daemon |
| REFLECT | `reflect_engine.py` | Trade outcome analysis, convergence | CLI only (Phase 3) |
| JOURNAL | `journal_engine.py` | Structured trade journal | CLI only (Phase 3) |
| MEMORY | `memory_engine.py` | Playbook per instrument/signal | CLI only (Phase 3) |
| LESSON | `lesson_engine.py` | Verbatim trade post-mortems. Persistence in `common/memory.py` (lessons table + FTS5). | Fully wired end-to-end. `lesson_author` iterator consumes closed positions. |
| THESIS_CHALLENGER | `thesis_challenger.py` | Catalyst-vs-invalidation pattern matcher | Wired to daemon (all tiers, alert-only) |
| THESIS_UPDATER | `thesis_updater.py` | Haiku-powered news -> conviction adjustment | Wired to daemon (kill switch OFF at ship) |
| CONTEXT | `context_engine.py` | Intent classification + data pre-fetch | Kill switch OFF at ship |
| LAB | `lab_engine.py` | Strategy development pipeline | Kill switch OFF at ship. CLI: `hl lab` |
| ARCHITECT | `architect_engine.py` | Mechanical self-improvement proposals | Kill switch OFF at ship. CLI: `hl architect` |
| OIL_BOTPATTERN | `oil_botpattern.py` | Sub-system 5 strategy engine | Kill switch OFF at ship |
| BOT_CLASSIFIER | `bot_classifier.py` | Sub-system 4 move classification | Kill switch OFF at ship |
| HEATMAP | `heatmap.py` | Sub-system 3 liquidity zones | Kill switch OFF at ship |
| SUPPLY_LEDGER | `supply_ledger.py` | Sub-system 2 disruption aggregation | Kill switch OFF at ship |

## Key Utilities

| Module | Purpose |
|--------|---------|
| `candle_cache.py` | OHLCV SQLite cache — **v3 critical path** (AI agent depends on this) |
| `radar_technicals.py` | EMA, RSI, ADX, ATR calculations |
| `trailing_stop.py` | Trailing stop price computation |
| `reconciliation.py` | Position reconciliation |
| `entry_critic.py` | Trade entry grading with lesson recall |
| `action_queue.py` | Operator ritual queue (nudge system) |

**Deep dive:** [docs/wiki/components/conviction-engine.md](../docs/wiki/components/conviction-engine.md)

## Learning Paths

- [Oil Bot-Pattern](../docs/wiki/learning-paths/oil-botpattern.md) — sub-systems 1-6 architecture and data flow
- [Thesis to Order](../docs/wiki/learning-paths/thesis-to-order.md) — conviction engine, sizing, order placement
- [Understanding Data Flow](../docs/wiki/learning-paths/understanding-data-flow.md) — how engines connect to iterators

## Gotchas

- `candle_cache.py` changes affect AI agent tool responses
- Engines are pure computation — daemon iterators call them, never the reverse
