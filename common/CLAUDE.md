# common/ — Shared Utilities + Infrastructure

Foundational utilities used by every other package. ~35 modules. The `models` module alone has 39 importers.

## Key Files

| File | Purpose |
|------|---------|
| `models.py` | Data structures (MarketSnapshot, StrategyContext, etc.) — 39 importers |
| `market_snapshot.py` | `build_snapshot()` + `render_snapshot()` + `render_signal_summary()` — full signal engine |
| `context_harness.py` | Relevance-scored context assembly, 3500 token budget, position-aware |
| `tools.py` | **Unified tool core** — 11 pure functions returning dicts (status, live_price, etc.) |
| `code_tool_parser.py` | **AST-based Python code parser** — parses tool calls from free model code blocks |
| `tool_renderers.py` | Compact AI renderer for tool output (42 tokens avg per tool) |
| `renderer.py` | **UI portability** — Renderer ABC + TelegramRenderer + BufferRenderer |
| `telemetry.py` | TelemetryRecorder + **HealthWindow** (Passivbot-style error budget) |
| `watchlist.py` | Centralized watchlist — single source for tracked markets, CRUD, HL search |
| `thesis.py` | ThesisState dataclass — shared contract between AI and execution |
| `conviction_engine.py` | Conviction bands → position sizing (Druckenmiller model) |
| `credentials.py` | Pluggable key backends: OWS → Keychain → Encrypted → Env → File |
| `account_resolver.py` | Wallet address resolution |
| `authority.py` | Per-asset delegation: agent vs manual vs off |
| `diagnostics.py` | Tool call logging, error tracking, chat logging |
| `memory.py` | SQLite-based 6-table action/event log |
| `memory_consolidator.py` | Event compression for context injection |
| `venue_adapter.py` | Abstract exchange interface (Protocol pattern) |
| `heartbeat.py` | Simplified 2-min monitoring (launchd stopgap) |

## Signal Engine Pipeline

`market_snapshot.py` is the core:
1. `build_snapshot(coin, cache, price)` — computes indicators across 1h/4h/1d
2. `render_snapshot(snap, detail)` — brief/standard/full text output
3. `render_signal_summary(snap, position)` — **actionable analysis**: exhaustion, divergence, multi-TF confluence, volume flow, position guidance

Used by: `/market` command, AI LIVE CONTEXT, daemon MarketStructure iterator.

## Tool Core (common/tools.py)

11 functions returning dicts. Single source of truth for tool logic:
- READ: `status()`, `live_price()`, `analyze_market()`, `market_brief()`, `check_funding()`, `get_orders()`, `trade_journal()`, `thesis_state()`, `daemon_health()`
- WRITE: `place_trade()`, `update_thesis()`

Consumed by: AI agent (via code_tool_parser), Telegram commands (future), agent_tools.py (backward compat).

## Renderer Interface (common/renderer.py)

`Renderer` ABC for UI portability:
- `TelegramRenderer` — wraps tg_send functions (production)
- `BufferRenderer` — captures output for tests and future web API
- 5 commands migrated: cmd_status, cmd_price, cmd_orders, cmd_health, cmd_menu

## Health Monitoring (common/telemetry.py)

- `TelemetryRecorder` — per-cycle metrics, writes to state/telemetry.json
- `HealthWindow` — Passivbot-style 15min sliding window with error budget (10 errors max)
- Wired into daemon Clock: records errors + order events, auto-downgrades on budget exhaustion

## Current Status (v3.2)
- All modules production-ready
- Signal engine: 1h/4h/1d with candle refresh
- Tools: 11 core functions, AST parser for free models
- Renderer: ABC exists, 5 commands migrated
- Health: HealthWindow live in daemon, reporting to telemetry.json
- 1694 tests passing
