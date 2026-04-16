# common/ — Shared Utilities + Infrastructure

Foundational utilities used by every other package. The `models` module is the most-imported file in the codebase.

## Key Files

| File | Purpose |
|------|---------|
| `models.py` | Data structures (MarketSnapshot, StrategyContext, etc.) |
| `config_schema.py` | Pydantic config schema — typed validation for all YAML/JSON configs |
| `market_snapshot.py` | `build_snapshot()` + `render_signal_summary()` — full signal engine |
| `renderer.py` | UI portability — Renderer ABC + TelegramRenderer + BufferRenderer |
| `telemetry.py` | TelemetryRecorder + HealthWindow (error budget) |
| `watchlist.py` | Centralized watchlist — single source for tracked markets |
| `thesis.py` | ThesisState dataclass — shared contract between AI and execution |
| `credentials.py` | Pluggable key backends: OWS -> Keychain -> Encrypted -> Env -> File |
| `authority.py` | Per-asset delegation: agent vs manual vs off |
| `markets.py` | `MarketRegistry` — reads `data/config/markets.yaml`, normalizes coin names (handles `xyz:` prefix), enforces per-instrument direction rules |
| `memory.py` | Canonical owner of `data/memory/memory.db`. Schema migration, FTS5 lessons table, event/learning/snapshot/lesson helpers |
| `memory_consolidator.py` | Event compression + trim_learnings_file for agent memory rolling trim |
| `venue_adapter.py` | Venue abstraction layer for exchange connectivity |
| `account_state.py` | Account state resolution and caching |
| `exchange_helpers.py` | Generic exchange data helpers — funding, OI, price change (interface-agnostic) |

## Moved Out During Domain Refactor

These were in `common/` but are now in their proper packages:

| File | New Location |
|------|-------------|
| `context_harness.py` | `agent/context_harness.py` |
| `tools.py` | `agent/tool_functions.py` |
| `code_tool_parser.py` | `agent/code_tool_parser.py` |
| `tool_renderers.py` | `agent/tool_renderers.py` |
| `conviction_engine.py` | `trading/conviction_engine.py` |
| `heartbeat.py` | `trading/heartbeat.py` |

**Deep dive:** [docs/wiki/architecture.md](../docs/wiki/architecture.md) | [docs/wiki/components/](../docs/wiki/components/)

## Learning Paths

- [Understanding Config](../docs/wiki/learning-paths/understanding-config.md) — config schema, validation, kill switches
- [Understanding Data Flow](../docs/wiki/learning-paths/understanding-data-flow.md) — how data structures move through the system
- [Thesis to Order](../docs/wiki/learning-paths/thesis-to-order.md) — conviction engine, thesis state, sizing

## Gotchas

- `candle_cache.py` is at `engines/data/candle_cache.py` — AI agent tools depend on it
- Dual-write requirement: ALL key storage must write to OWS + Keychain
