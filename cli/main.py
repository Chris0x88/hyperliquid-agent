"""hl — Autonomous Hyperliquid trading CLI."""
from __future__ import annotations

import sys
from pathlib import Path

import typer

# Ensure project root is importable
_root = str(Path(__file__).resolve().parent.parent)
if _root not in sys.path:
    sys.path.insert(0, _root)

app = typer.Typer(
    name="hl",
    help="Autonomous Hyperliquid trader — direct HL API execution.",
    no_args_is_help=True,
    add_completion=False,
)

from cli.commands.run import run_cmd
from cli.commands.status import status_cmd
from cli.commands.trade import trade_cmd
from cli.commands.account import account_cmd
from cli.commands.strategies import strategies_cmd
from cli.commands.guard import guard_app
from cli.commands.radar import radar_app
from cli.commands.pulse import pulse_app
from cli.commands.apex import apex_app
from cli.commands.reflect import reflect_app
from cli.commands.wallet import wallet_app
from cli.commands.check import setup_app
from cli.commands.mcp import mcp_app
from cli.commands.skills import skills_app
from cli.commands.journal import journal_app
from cli.commands.keys import keys_app
from cli.commands.markets import markets_app
from cli.commands.data import data_app
from cli.commands.backtest import backtest_app
from cli.commands.daemon import daemon_app
from cli.commands.heartbeat_cmd import heartbeat_app
from cli.commands.telegram import telegram_app
from cli.commands.help_registry import commands_app
from cli.commands.lab import app as lab_app
# architect was archived 2026-04-17 (commit 14cc3e2 — superseded by Sub-6 L2
# oil_botpattern_reflect). Import is optional so the daemon doesn't crash
# when the archived module is missing. If the operator un-archives it later,
# the import + add_typer below resume working.
try:
    from cli.commands.architect import app as architect_app  # type: ignore
    _has_architect = True
except ModuleNotFoundError:
    _has_architect = False

app.command("run", help="Start autonomous trading with a strategy")(run_cmd)
app.command("status", help="Show positions, PnL, and risk state")(status_cmd)
app.command("trade", help="Place a single manual order")(trade_cmd)
app.command("account", help="Show HL account state")(account_cmd)
app.command("strategies", help="List available strategies")(strategies_cmd)
app.add_typer(guard_app, name="guard", help="Guard trailing stop system")
app.add_typer(radar_app, name="radar", help="Radar — screen HL perps for setups")
app.add_typer(pulse_app, name="pulse", help="Pulse — detect assets with capital inflow")
app.add_typer(apex_app, name="apex", help="APEX — autonomous multi-slot trading")
app.add_typer(reflect_app, name="reflect", help="Reflect — performance review and self-improvement")
app.add_typer(wallet_app, name="wallet", help="Encrypted keystore wallet management")
app.add_typer(setup_app, name="setup", help="Environment validation and setup")
app.add_typer(mcp_app, name="mcp", help="MCP server — AI agent tool discovery")
app.add_typer(skills_app, name="skills", help="Skill discovery and registry")
app.add_typer(journal_app, name="journal", help="Trade journal — structured position records with reasoning")
app.add_typer(keys_app, name="keys", help="Unified key management across backends")
app.add_typer(markets_app, name="markets", help="Browse, search, and filter all HL perpetual contracts")
app.add_typer(data_app, name="data", help="Historical data — fetch, cache, export")
app.add_typer(backtest_app, name="backtest", help="Backtest strategies against historical data")
app.add_typer(daemon_app, name="daemon", help="Daemon — monitoring and trading loop")
app.add_typer(heartbeat_app, name="heartbeat", help="Heartbeat — position auditor and risk monitor")
app.add_typer(telegram_app, name="telegram", help="Telegram bot — real-time commands, zero AI credits")
app.add_typer(commands_app, name="commands", help="List all commands (short/long form)")
app.add_typer(lab_app, name="lab", help="Lab — strategy development pipeline")
if _has_architect:
    app.add_typer(architect_app, name="architect", help="Architect — mechanical self-improvement")


def main():
    app()


if __name__ == "__main__":
    main()
