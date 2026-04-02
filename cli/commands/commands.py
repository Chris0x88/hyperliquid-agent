"""hl commands — list all available commands with descriptions."""
from __future__ import annotations

from typing import Optional

import typer

commands_app = typer.Typer(invoke_without_command=True)

# Master command registry — single source of truth.
# Format: (command, short_alias, description, category)
COMMAND_REGISTRY = [
    # ── Core Trading ─────────────────────────────────────────
    ("hl daemon start", "hds", "Start the trading daemon", "trading"),
    ("hl daemon stop", None, "Stop the running daemon", "trading"),
    ("hl daemon status", "hdst", "Show daemon status and strategies", "trading"),
    ("hl daemon once", None, "Run a single daemon tick", "trading"),
    ("hl daemon tier", "hdt", "Show or change daemon tier", "trading"),
    ("hl daemon strategies", None, "List active strategies in roster", "trading"),
    ("hl daemon add", "hda", "Add a strategy to the roster", "trading"),
    ("hl daemon remove", None, "Remove a strategy from the roster", "trading"),
    ("hl daemon pause", None, "Pause a strategy without removing", "trading"),
    ("hl daemon resume", None, "Resume a paused strategy", "trading"),
    ("hl run", "hr", "Run a strategy directly (no daemon)", "trading"),
    ("hl trade", "ht", "Place a single manual order", "trading"),

    # ── Monitoring ───────────────────────────────────────────
    ("hl status", "hs", "Show positions, PnL, and risk state", "monitoring"),
    ("hl account", "ha", "Show HL account state", "monitoring"),
    ("hl strategies", None, "List available strategies", "monitoring"),
    ("hl markets", "hm", "Browse and search all HL perps", "monitoring"),

    # ── Telegram ─────────────────────────────────────────────
    ("hl telegram start", "hts", "Start real-time Telegram bot (2s polling)", "telegram"),
    ("hl telegram stop", None, "Stop the Telegram bot", "telegram"),
    ("hl telegram status", None, "Check if Telegram bot is running", "telegram"),

    # ── Data & Backtesting ───────────────────────────────────
    ("hl data fetch", "hdf", "Fetch and cache historical candles", "data"),
    ("hl data stats", None, "Show cache statistics", "data"),
    ("hl data export", None, "Export cached data to CSV", "data"),
    ("hl backtest run", "hbr", "Backtest a strategy against history", "data"),

    # ── Scanning ─────────────────────────────────────────────
    ("hl radar once", None, "Screen all HL perps for setups", "scanning"),
    ("hl radar run", None, "Continuous radar scanning", "scanning"),
    ("hl pulse once", None, "Detect capital inflow signals", "scanning"),
    ("hl pulse run", None, "Continuous pulse monitoring", "scanning"),
    ("hl guard run", None, "Run trailing stop guard on a position", "scanning"),
    ("hl reflect run", None, "Performance review and self-improvement", "scanning"),

    # ── Key Management ───────────────────────────────────────
    ("hl keys import", "hki", "Import a private key (OWS/Keychain)", "keys"),
    ("hl keys list", "hkl", "List all stored keys", "keys"),
    ("hl keys migrate", None, "Migrate key between backends", "keys"),
    ("hl wallet auto", None, "Auto-detect and configure wallet", "keys"),

    # ── Infrastructure ───────────────────────────────────────
    ("hl setup check", None, "Validate environment and dependencies", "infra"),
    ("hl mcp serve", None, "Start MCP server for AI agents", "infra"),
    ("hl journal", None, "View trade journal", "infra"),
    ("hl commands", "hc", "This command — list all commands", "infra"),
]

CATEGORIES = {
    "trading": "Trading",
    "monitoring": "Monitoring",
    "telegram": "Telegram",
    "data": "Data & Backtesting",
    "scanning": "Scanning & Analysis",
    "keys": "Key Management",
    "infra": "Infrastructure",
}

# Telegram command registry (for /commands in Telegram bot)
TELEGRAM_COMMANDS = [
    # Trading
    ("/status", "Portfolio overview"),
    ("/position", "Positions + risk + authority"),
    ("/market", "Technicals, funding, OI"),
    ("/pnl", "Profit & loss breakdown"),
    ("/price", "Quick prices"),
    ("/orders", "Open orders"),
    # Charts
    ("/chartoil", "Oil price chart (hours)"),
    ("/chartbtc", "BTC price chart"),
    ("/chartgold", "Gold price chart"),
    ("/watchlist", "All markets + prices"),
    ("/powerlaw", "BTC power law model"),
    # Agent Control
    ("/authority", "Who manages what"),
    ("/delegate", "Hand asset to agent"),
    ("/reclaim", "Take asset back"),
    # Vault
    ("/rebalancer", "Rebalancer status/start/stop"),
    ("/rebalance", "Force vault rebalance"),
    # System
    ("/models", "AI model selection"),
    ("/memory", "Memory system status"),
    ("/health", "App health check"),
    ("/diag", "Error diagnostics"),
    ("/bug", "Report a bug"),
    ("/todo", "Add or list todos"),
    ("/feedback", "Submit feedback"),
    ("/guide", "How to use this bot"),
    ("/help", "Full command list"),
]


@commands_app.callback(invoke_without_command=True)
def commands_list(
    ctx: typer.Context,
    long: bool = typer.Option(False, "--long", "-l", help="Show full details with aliases"),
    category: Optional[str] = typer.Option(None, "--cat", "-c", help="Filter by category"),
    search: Optional[str] = typer.Option(None, "--search", "-s", help="Search commands"),
):
    """List all available commands."""
    if ctx.invoked_subcommand is not None:
        return

    filtered = COMMAND_REGISTRY

    if category:
        filtered = [c for c in filtered if c[3] == category.lower()]
        if not filtered:
            typer.echo(f"No commands in category '{category}'. Valid: {', '.join(CATEGORIES.keys())}")
            raise typer.Exit(1)

    if search:
        q = search.lower()
        filtered = [c for c in filtered if q in c[0].lower() or q in c[2].lower()]
        if not filtered:
            typer.echo(f"No commands matching '{search}'.")
            raise typer.Exit(1)

    if long:
        _print_long(filtered)
    else:
        _print_short(filtered)

    typer.echo(f"\n{len(filtered)} commands. Use --long for aliases, --cat <name> to filter.")


def _print_short(cmds):
    current_cat = None
    for cmd, alias, desc, cat in cmds:
        if cat != current_cat:
            current_cat = cat
            typer.echo(f"\n  {CATEGORIES.get(cat, cat).upper()}")
        short = f" ({alias})" if alias else ""
        typer.echo(f"    {cmd:<30} {desc}{short}")


def _print_long(cmds):
    current_cat = None
    for cmd, alias, desc, cat in cmds:
        if cat != current_cat:
            current_cat = cat
            typer.echo(f"\n{'=' * 50}")
            typer.echo(f"  {CATEGORIES.get(cat, cat).upper()}")
            typer.echo(f"{'=' * 50}")
        typer.echo(f"\n  {cmd}")
        if alias:
            typer.echo(f"    Alias: {alias}")
        typer.echo(f"    {desc}")


def get_commands_text(long: bool = False, category: Optional[str] = None) -> str:
    """Get commands as text (for Telegram /commands)."""
    filtered = COMMAND_REGISTRY
    if category:
        filtered = [c for c in filtered if c[3] == category.lower()]

    if not long and not category:
        # Telegram commands grouped by section
        sections = {
            "Trading": [], "Charts": [], "Agent Control": [],
            "Vault": [], "System": [],
        }
        section_order = ["Trading", "Charts", "Agent Control", "Vault", "System"]
        current_section = None
        for tc, td in TELEGRAM_COMMANDS:
            # Infer section from position in list
            if tc in ("/status", "/position", "/market", "/pnl", "/price", "/orders"):
                sections["Trading"].append((tc, td))
            elif tc in ("/chartoil", "/chartbtc", "/chartgold", "/watchlist", "/powerlaw"):
                sections["Charts"].append((tc, td))
            elif tc in ("/authority", "/delegate", "/reclaim"):
                sections["Agent Control"].append((tc, td))
            elif tc in ("/rebalancer", "/rebalance"):
                sections["Vault"].append((tc, td))
            else:
                sections["System"].append((tc, td))

        lines = ["*Commands*", ""]
        for section in section_order:
            cmds = sections.get(section, [])
            if cmds:
                lines.append(f"*{section}*")
                for tc, td in cmds:
                    lines.append(f"  {tc} — {td}")
                lines.append("")

        lines.append("Type anything for AI chat")
        lines.append("`/commands long` — full CLI list")
        return "\n".join(lines)

    lines = ["*CLI Commands*", ""]
    current_cat = None
    for cmd, alias, desc, cat in filtered:
        if cat != current_cat:
            current_cat = cat
            lines.append(f"\n*{CATEGORIES.get(cat, cat)}*")
        short = f" (`{alias}`)" if alias and long else ""
        lines.append(f"  `{cmd}` — {desc}{short}")

    lines.append(f"\n`{len(filtered)}` commands")
    return "\n".join(lines)
