# common/ — Shared Utilities + Infrastructure

Foundational utilities used by every other package. The `models` module is the most-imported file in the codebase.

## Key Files

| File | Purpose |
|------|---------|
| `models.py` | Data structures (MarketSnapshot, StrategyContext, etc.) |
| `market_snapshot.py` | `build_snapshot()` + `render_signal_summary()` — full signal engine |
| `context_harness.py` | Relevance-scored context assembly with token budget |
| `tools.py` | Unified tool core — pure functions returning dicts |
| `code_tool_parser.py` | AST-based parser for free model code blocks |
| `tool_renderers.py` | Compact AI renderer for tool output |
| `renderer.py` | UI portability — Renderer ABC + TelegramRenderer + BufferRenderer |
| `telemetry.py` | TelemetryRecorder + HealthWindow (error budget) |
| `watchlist.py` | Centralized watchlist — single source for tracked markets |
| `thesis.py` | ThesisState dataclass — shared contract between AI and execution |
| `conviction_engine.py` | Conviction bands → position sizing |
| `credentials.py` | Pluggable key backends: OWS → Keychain → Encrypted → Env → File |
| `authority.py` | Per-asset delegation: agent vs manual vs off |
| `heartbeat.py` | Simplified 2-min monitoring (launchd) |
| `memory.py` | Canonical owner of `data/memory/memory.db`. `_init()` migrates schema for all tables (events, learnings, observations, action_log, execution_traces, account_snapshots, summaries, lessons + `lessons_fts` FTS5). Module-level helpers: `log_event`, `log_learning`, `log_account_snapshot`, `log_lesson`, `get_lesson`, `search_lessons` (BM25), `set_lesson_review`. FTS5 input sanitized via `_fts5_escape_query`. |
| `memory_consolidator.py` | Event compression + trim_learnings_file for agent memory rolling trim |

**Deep dive:** [docs/wiki/architecture.md](../docs/wiki/architecture.md) | [docs/wiki/components/](../docs/wiki/components/)

## Gotchas

- `candle_cache.py` (in `modules/`) is on the v3 critical path — AI agent tools depend on it
- Dual-write requirement: ALL key storage must write to OWS + Keychain
