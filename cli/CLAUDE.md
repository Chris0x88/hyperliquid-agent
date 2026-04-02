# cli/ — CLI Commands + MCP Server

23 CLI commands accessible via `hl <command>`. Star topology — each command is independent, all routed through `main.py`. Also contains the MCP server that powers the OpenClaw agent.

## Entry Point

`cli/main.py` — Typer app with 23 subcommands. Run via `hl` (installed via pyproject.toml `[project.scripts]`).

## Command Inventory

| Command | File | Purpose |
|---------|------|---------|
| `hl run` | `commands/run.py` | Start autonomous trading (legacy engine) |
| `hl status` | `commands/status.py` | Show positions, PnL, risk |
| `hl trade` | `commands/trade.py` | Manual order placement |
| `hl account` | `commands/account.py` | HL account state |
| `hl strategies` | `commands/strategies.py` | List registered strategies |
| `hl guard` | `commands/guard.py` | Trailing stop system |
| `hl radar` | `commands/radar.py` | Market scanner |
| `hl pulse` | `commands/pulse.py` | Capital inflow detection |
| `hl apex` | `commands/apex.py` | Multi-slot trading |
| `hl reflect` | `commands/reflect.py` | Performance review |
| `hl wallet` | `commands/wallet.py` | Keystore management |
| `hl setup` | `commands/setup.py` | Environment validation |
| `hl mcp` | `commands/mcp.py` | MCP server (`hl mcp serve`) |
| `hl skills` | `commands/skills.py` | Skill discovery |
| `hl journal` | `commands/journal.py` | Trade journal |
| `hl keys` | `commands/keys.py` | Unified key management |
| `hl markets` | `commands/markets.py` | Browse/search HL perps |
| `hl data` | `commands/data.py` | Fetch/cache historical |
| `hl backtest` | `commands/backtest.py` | Backtest strategies |
| `hl daemon` | `commands/daemon.py` | Monitoring loop |
| `hl heartbeat` | `commands/heartbeat_cmd.py` | Position auditor |
| `hl telegram` | `commands/telegram.py` | Telegram bot control |
| `hl commands` | `commands/commands.py` | List all commands |

## MCP Server

`cli/mcp_server.py` — FastMCP server with 17 tools (Phase 2 adds 2 more).

**Launch:** `hl mcp serve` or `.venv/bin/python -m cli.main mcp serve`

**Current tools:** market_context, account, status, analyze, get_candles, agent_memory, trade_journal, trade, log_bug, log_feedback, diagnostic_report, daemon_status, strategies, setup_check, cache_stats, run_strategy, daemon_start

**Phase 2 additions:** update_thesis, live_price

All tool responses capped at 3000 chars. Token budgeting via chars/4 estimation.

## Other Key Files

| File | Purpose |
|------|---------|
| `telegram_bot.py` | Commands Bot — polls Telegram, 22 fixed handlers, zero AI |
| `telegram_handler.py` | Legacy handler (not actively used) |
| `strategy_registry.py` | 27 registered strategies (module:class paths) |
| `config.py` | TradingConfig dataclass + YAML loading |
| `engine.py` | Legacy trading engine (single-strategy) |
| `hl_adapter.py` | DirectHLProxy wrapper for the SDK |
| `chart_engine.py` | Price chart generation (matplotlib) |
| `mcp_server.py` | FastMCP server for OpenClaw agent |

## Upstream
- `main.py` routes to all commands
- OpenClaw gateway calls MCP server
- launchd can launch telegram_bot.py

## Downstream
- Commands call into `common/`, `modules/`, `parent/`
- MCP server calls into `common/thesis.py`, `parent/hl_proxy.py`, `modules/`

## Current Status
- All 23 commands work
- MCP server starts with 17 tools (mcp package installed this session)
- Commands Bot running with /chartoil shorthand fix
- Daemon command works but daemon not running as primary

## Testing
```bash
.venv/bin/python -m pytest tests/test_config.py tests/test_engine.py tests/test_strategy_registry.py -x -q
```
