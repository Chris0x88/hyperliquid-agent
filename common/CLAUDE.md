# common/ — Shared Utilities + Infrastructure

Foundational utilities used by every other package. The `models` module is the most-imported file in the codebase.

## Key Files

| File | Purpose |
|------|---------|
| `models.py` | Data structures (MarketSnapshot, StrategyContext, etc.) |
| `config_schema.py` | Pydantic config schema — typed validation for all YAML/JSON configs |
| `market_snapshot.py` | `build_snapshot()` + `render_signal_summary()` — full signal engine |
| `context_harness.py` | Relevance-scored context assembly with token budget |
| `tools.py` | Unified tool core — pure functions returning dicts |
| `code_tool_parser.py` | AST-based parser for free model code blocks |
| `tool_renderers.py` | Compact AI renderer for tool output |
| `renderer.py` | UI portability — Renderer ABC + TelegramRenderer + BufferRenderer |
| `telemetry.py` | TelemetryRecorder + HealthWindow (error budget) |
| `watchlist.py` | Centralized watchlist — single source for tracked markets |
| `thesis.py` | ThesisState dataclass — shared contract between AI and execution |
| `conviction_engine.py` | Conviction bands -> position sizing |
| `credentials.py` | Pluggable key backends: OWS -> Keychain -> Encrypted -> Env -> File |
| `authority.py` | Per-asset delegation: agent vs manual vs off |
| `markets.py` | `MarketRegistry` — reads `data/config/markets.yaml`, normalizes coin names (handles `xyz:` prefix), enforces per-instrument direction rules |
| `heartbeat.py` | Simplified 2-min monitoring (launchd) |
| `memory.py` | Canonical owner of `data/memory/memory.db`. Schema migration, FTS5 lessons table, event/learning/snapshot/lesson helpers |
| `memory_consolidator.py` | Event compression + trim_learnings_file for agent memory rolling trim |
| `venue_adapter.py` | Venue abstraction layer for exchange connectivity |
| `account_state.py` | Account state resolution and caching |

**Deep dive:** [docs/wiki/architecture.md](../docs/wiki/architecture.md) | [docs/wiki/components/](../docs/wiki/components/)

## Learning Paths

- [Understanding Config](../docs/wiki/learning-paths/understanding-config.md) — config schema, validation, kill switches
- [Understanding Data Flow](../docs/wiki/learning-paths/understanding-data-flow.md) — how data structures move through the system
- [Thesis to Order](../docs/wiki/learning-paths/thesis-to-order.md) — conviction engine, thesis state, sizing

## Gotchas

- `candle_cache.py` (in `modules/`) is on the v3 critical path — AI agent tools depend on it
- Dual-write requirement: ALL key storage must write to OWS + Keychain
