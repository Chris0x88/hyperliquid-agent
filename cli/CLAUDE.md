# cli/ — CLI Entry Point + Utility Commands

Typer-based CLI entry point and utility files. After domain refactor, this is the slim remainder — Telegram, agent, and daemon extracted to their own packages.

## Key Files

| File | Purpose |
|------|---------|
| `main.py` | Typer CLI entry point |
| `config.py` | TradingConfig |
| `engine.py` | TradingEngine |
| `mcp_server.py` | MCP server for OpenClaw agent |
| `commands/` | 26 Typer subcommand files (daemon, wallet, keys, markets, etc.) |

## Other Files

| File | Purpose |
|------|---------|
| `display.py` | Terminal/ANSI display helpers |
| `order_manager.py` | Order management |
| `strategy_registry.py` | Strategy registry |
| `chart_engine.py` | Chart generation |
| `daily_report.py` | Daily report generation |
| `risk_monitor.py` | Risk monitoring |
| `keystore.py` | Keychain access |
| `research.py` | Research tools |

## See Also

- **Telegram bot**: `telegram/CLAUDE.md`
- **AI agent**: `agent/CLAUDE.md`
- **Daemon**: `daemon/CLAUDE.md`
