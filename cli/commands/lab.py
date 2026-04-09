"""CLI commands for the Lab Engine — strategy development pipeline.

Usage:
    hl lab status              — show all experiments by status
    hl lab discover <market>   — profile market and create candidate experiments
    hl lab create <market> <strategy> — create a specific experiment
    hl lab backtest <exp-id>   — run backtest for an experiment
    hl lab promote <exp-id>    — promote graduated experiment to production
    hl lab retire <exp-id>     — retire an experiment
    hl lab archetypes          — list available strategy archetypes
"""
from __future__ import annotations

import typer

app = typer.Typer(help="Strategy development lab")


@app.command()
def status():
    """Show all experiments grouped by status."""
    from modules.lab_engine import LabEngine
    lab = LabEngine()

    if not lab.enabled:
        typer.echo("Lab Engine is DISABLED. Enable in data/config/lab.json")
        return

    info = lab.get_status()
    typer.echo(f"Lab Engine — {info['total']} experiments\n")

    for status_name, experiments in info.get("by_status", {}).items():
        typer.echo(f"  [{status_name.upper()}]")
        for e in experiments:
            metrics = e.get("metrics", {})
            sharpe = metrics.get("sharpe", 0) if metrics else 0
            typer.echo(f"    {e['id']}: {e['strategy']} on {e['market']} (sharpe={sharpe:.2f})")
        typer.echo("")


@app.command()
def discover(market: str):
    """Profile a market and create candidate experiments."""
    from modules.lab_engine import LabEngine
    lab = LabEngine()

    if not lab.enabled:
        typer.echo("Lab Engine is DISABLED. Enable in data/config/lab.json")
        return

    created = lab.discover(market.upper())
    if created:
        typer.echo(f"Created {len(created)} experiments for {market}:")
        for eid in created:
            exp = lab.get_experiment(eid)
            if exp:
                typer.echo(f"  {exp.id}: {exp.strategy}")
    else:
        typer.echo(f"No new experiments created for {market} (may already exist or no matching archetypes)")


@app.command()
def create(market: str, strategy: str):
    """Create a specific experiment."""
    from modules.lab_engine import LabEngine
    lab = LabEngine()

    if not lab.enabled:
        typer.echo("Lab Engine is DISABLED. Enable in data/config/lab.json")
        return

    exp = lab.create_experiment(market.upper(), strategy)
    if exp:
        typer.echo(f"Created: {exp.id} — {exp.strategy} on {exp.market}")
    else:
        typer.echo(f"Failed to create experiment. Check strategy name (use 'hl lab archetypes')")


@app.command()
def backtest(exp_id: str):
    """Run backtest for an experiment."""
    from modules.lab_engine import LabEngine
    lab = LabEngine()

    if not lab.enabled:
        typer.echo("Lab Engine is DISABLED.")
        return

    typer.echo(f"Running backtest for {exp_id}...")
    metrics = lab.run_backtest(exp_id)
    if metrics:
        typer.echo("Results:")
        for k, v in metrics.items():
            typer.echo(f"  {k}: {v:.4f}")
        exp = lab.get_experiment(exp_id)
        if exp:
            typer.echo(f"\nStatus: {exp.status}")
    else:
        typer.echo("Backtest failed or experiment not found.")


@app.command()
def promote(exp_id: str):
    """Promote a graduated experiment to production."""
    from modules.lab_engine import LabEngine
    lab = LabEngine()

    if lab.promote_to_production(exp_id):
        typer.echo(f"Experiment {exp_id} promoted to PRODUCTION (params frozen)")
    else:
        typer.echo(f"Cannot promote {exp_id} — must be in 'graduated' status")


@app.command()
def retire(exp_id: str):
    """Retire an experiment."""
    from modules.lab_engine import LabEngine
    lab = LabEngine()

    if lab.retire_experiment(exp_id):
        typer.echo(f"Experiment {exp_id} retired")
    else:
        typer.echo(f"Experiment {exp_id} not found")


@app.command()
def archetypes():
    """List available strategy archetypes."""
    from modules.lab_engine import STRATEGY_ARCHETYPES
    typer.echo("Available strategy archetypes:\n")
    for name, arch in STRATEGY_ARCHETYPES.items():
        typer.echo(f"  {name}")
        typer.echo(f"    {arch['description']}")
        typer.echo(f"    Signals: {', '.join(arch.get('signals', []))}")
        typer.echo(f"    Suitable for: {', '.join(arch.get('suitable_for', []))}")
        typer.echo("")
