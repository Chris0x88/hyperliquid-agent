"""hl lab — strategy development pipeline.

Discover markets, test strategies, graduate winners to production.

Commands:
    hl lab status     — show pipeline status
    hl lab discover   — analyze a market and create experiments
    hl lab create     — manually create an experiment
    hl lab list       — list all experiments by stage
    hl lab promote    — manually advance an experiment
    hl lab lock       — lock a graduated strategy (prevent changes)
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from typing import Optional

import typer

lab_app = typer.Typer(no_args_is_help=True)


def _ensure_root():
    root = str(Path(__file__).resolve().parent.parent.parent)
    if root not in sys.path:
        sys.path.insert(0, root)


@lab_app.command("status")
def lab_status(json_output: bool = typer.Option(False, "--json", help="Output as JSON")):
    """Show Lab pipeline status — active experiments, graduated, by stage."""
    _ensure_root()
    from modules.lab_engine import LabEngine

    engine = LabEngine()
    status = engine.status()

    if json_output:
        typer.echo(json.dumps(status, indent=2))
        return

    typer.echo(f"\nLab Pipeline — {status['total_experiments']} experiments\n")

    by_stage = status.get("by_stage", {})
    for stage, count in by_stage.items():
        marker = "*" if stage in ("backtest", "paper_trade") else " "
        typer.echo(f"  {marker} {stage:<15} {count}")

    active = status.get("active", [])
    if active:
        typer.echo(f"\nActive ({len(active)}):")
        for exp in active:
            typer.echo(f"  {exp['market']:<20} {exp['strategy']:<25} "
                       f"stage={exp['stage']:<12} score={exp.get('score', 0):.2f}")

    graduated = status.get("graduated", [])
    if graduated:
        typer.echo(f"\nGraduated ({len(graduated)}):")
        for exp in graduated:
            typer.echo(f"  {exp['market']:<20} {exp['strategy']:<25} score={exp.get('score', 0):.2f}")

    if not active and not graduated:
        typer.echo("\n  No experiments yet. Run 'hl lab discover <market>' to start.")


@lab_app.command("discover")
def lab_discover(
    market: str = typer.Argument(..., help="Market to analyze (e.g., BTC-PERP, xyz:BRENTOIL)"),
    days: int = typer.Option(90, "--days", "-d", help="Days of history to analyze"),
):
    """Analyze a market's characteristics and auto-create experiments for matching strategies."""
    _ensure_root()
    from modules.lab_engine import LabEngine
    from modules.candle_cache import CandleCache

    coin = market.replace("-PERP", "").replace("xyz:", "")
    cache = CandleCache()
    end_ms = int(time.time() * 1000)
    start_ms = end_ms - (days * 86_400_000)

    typer.echo(f"Analyzing {market} ({days} days)...")

    candles = cache.get_candles(coin, "1h", start_ms, end_ms)
    if not candles:
        try:
            from modules.data_fetcher import DataFetcher
            fetcher = DataFetcher(cache=cache, testnet=False)
            fetcher.backfill(coin, "1h", days)
            candles = cache.get_candles(coin, "1h", start_ms, end_ms)
        except Exception as e:
            typer.echo(f"Error: Could not fetch data for {coin}: {e}", err=True)
            raise typer.Exit(1)

    if not candles:
        typer.echo(f"Error: No candle data available for {coin}", err=True)
        raise typer.Exit(1)

    engine = LabEngine()
    profile = engine.discover_market(market, candles)
    experiments = engine.create_experiments_from_profile(market, profile)

    typer.echo(f"\nMarket Profile: {market}")
    typer.echo(f"  Volatility (ann):    {profile.get('volatility_ann', 0):.2%}")
    typer.echo(f"  Trend strength:      {profile.get('trend_strength', 0):.4f}")
    typer.echo(f"  Mean reversion:      {profile.get('mean_reversion_score', 0):.4f}")
    typer.echo(f"  ATR (%):             {profile.get('atr_pct', 0):.2f}%")
    typer.echo(f"  Avg volume:          {profile.get('avg_volume', 0):,.0f}")
    typer.echo(f"  Archetypes:          {', '.join(profile.get('archetypes', []))}")
    typer.echo(f"  Candles analyzed:    {profile.get('candles_analyzed', 0)}")

    if experiments:
        typer.echo(f"\nCreated {len(experiments)} experiments:")
        for exp in experiments:
            typer.echo(f"  {exp.strategy:<25} stage={exp.stage}")
    else:
        typer.echo("\nNo new experiments (all combos already exist).")


@lab_app.command("create")
def lab_create(
    market: str = typer.Argument(..., help="Market (e.g., BTC-PERP)"),
    strategy: str = typer.Argument(..., help="Strategy name"),
):
    """Manually create a Lab experiment."""
    _ensure_root()
    from modules.lab_engine import LabEngine

    engine = LabEngine()
    exp = engine.create_experiment(market, strategy)
    typer.echo(f"Created: {exp.experiment_id}")
    typer.echo(f"  Market:   {market}")
    typer.echo(f"  Strategy: {strategy}")
    typer.echo(f"  Stage:    {exp.stage}")
    typer.echo(f"\nWill auto-progress: hypothesis -> backtest -> paper_trade -> graduated")


@lab_app.command("list")
def lab_list(
    stage: Optional[str] = typer.Option(None, "--stage", "-s", help="Filter by stage"),
    json_output: bool = typer.Option(False, "--json"),
):
    """List all experiments, optionally filtered by stage."""
    _ensure_root()
    from modules.lab_engine import LabEngine

    engine = LabEngine()
    exps = engine.get_by_stage(stage) if stage else engine.experiments

    if json_output:
        typer.echo(json.dumps([e.to_dict() for e in exps], indent=2))
        return

    if not exps:
        typer.echo("No experiments." + (f" (stage={stage})" if stage else ""))
        return

    typer.echo(f"\n{'Market':<20} {'Strategy':<25} {'Stage':<12} {'Score':<8} {'Backtests'}")
    typer.echo("-" * 80)
    for exp in exps:
        typer.echo(
            f"  {exp.market:<18} {exp.strategy:<25} {exp.stage:<12} "
            f"{exp.graduation_score:<8.2f} {len(exp.backtest_results)}"
        )


@lab_app.command("tick")
def lab_tick():
    """Run one Lab cycle manually (progress experiments through stages)."""
    _ensure_root()
    from modules.lab_engine import LabEngine

    engine = LabEngine()
    events = engine.tick()

    if events:
        typer.echo(f"{len(events)} events:")
        for ev in events:
            typer.echo(f"  [{ev.get('type')}] {ev.get('id', '')}: {ev.get('message', '')}")
    else:
        typer.echo("No events this tick.")

    status = engine.status()
    typer.echo(f"\nPipeline: {status['by_stage']}")
