"""hl strategies — list available strategies with visibility filtering."""
from __future__ import annotations

import sys
from pathlib import Path

import typer


def strategies_cmd(
    all: bool = typer.Option(False, "--all", "-a", help="Show featured + standard strategies"),
    advanced: bool = typer.Option(False, "--advanced", help="Show all strategies including advanced"),
):
    """List available trading strategies."""
    project_root = str(Path(__file__).resolve().parent.parent.parent)
    if project_root not in sys.path:
        sys.path.insert(0, project_root)

    from cli.strategy_registry import list_strategies

    if advanced:
        visibility = "advanced"
    elif all:
        visibility = "all"
    else:
        visibility = "featured"

    strategies = list_strategies(visibility)

    if not strategies:
        typer.echo("No strategies found.")
        return

    typer.echo(f"{'Name':<22} {'Visibility':<12} {'Description'}")
    typer.echo("-" * 80)
    for s in strategies:
        vis = s.get("visibility", "advanced")
        name = s["name"]
        desc = s["description"][:50]
        # Color: featured=green, standard=yellow, advanced=cyan
        if vis == "featured":
            typer.echo(f"\033[32m{name:<22}\033[0m {vis:<12} {desc}")
        elif vis == "standard":
            typer.echo(f"\033[33m{name:<22}\033[0m {vis:<12} {desc}")
        else:
            typer.echo(f"\033[36m{name:<22}\033[0m {vis:<12} {desc}")

    total = len(list_strategies("advanced"))
    shown = len(strategies)
    if shown < total:
        hidden = total - shown
        hint = "--all" if visibility == "featured" else "--advanced"
        typer.echo(f"\n{hidden} more strategies hidden. Use 'hl strategies {hint}' to see them.")
