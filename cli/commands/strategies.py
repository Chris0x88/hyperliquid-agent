"""hl strategies — list available strategies."""
from __future__ import annotations

import sys
from pathlib import Path

import typer


def strategies_cmd():
    """List available trading strategies."""
    project_root = str(Path(__file__).resolve().parent.parent.parent)
    if project_root not in sys.path:
        sys.path.insert(0, project_root)

    from cli.display import strategy_table
    from cli.strategy_registry import STRATEGY_REGISTRY, YEX_MARKETS

    typer.echo(strategy_table(STRATEGY_REGISTRY))
    typer.echo("")
    typer.echo("\033[1mYEX Markets (HIP-3)\033[0m")
    typer.echo(f"{'Name':<20} {'HL Coin':<15} {'Description'}")
    typer.echo(f"{'-'*20} {'-'*15} {'-'*40}")
    for name, info in sorted(YEX_MARKETS.items()):
        typer.echo(f"\033[36m{name:<20}\033[0m {info['hl_coin']:<15} {info['description']}")
