"""hl backtest — replay strategies against historical data."""
from __future__ import annotations

import sys
from pathlib import Path

import typer

backtest_app = typer.Typer(no_args_is_help=True)


def _ensure_path():
    project_root = str(Path(__file__).resolve().parent.parent.parent)
    if project_root not in sys.path:
        sys.path.insert(0, project_root)


@backtest_app.command("run")
def backtest_run(
    strategy: str = typer.Option(..., "--strategy", "-s", help="Strategy name (e.g., momentum_breakout, trend_follower)"),
    coin: str = typer.Option("BTC", "--coin", "-c", help="Coin to backtest"),
    interval: str = typer.Option("1h", "--interval", "-i", help="Candle interval"),
    days: int = typer.Option(90, "--days", "-d", help="Days of history to replay"),
    capital: float = typer.Option(10_000, "--capital", help="Starting capital ($)"),
    leverage: float = typer.Option(10.0, "--leverage", help="Max leverage"),
    fee_bps: float = typer.Option(3.5, "--fee-bps", help="Fee per trade in basis points"),
    chart: bool = typer.Option(True, "--chart/--no-chart", help="Generate equity curve chart"),
    json_output: bool = typer.Option(False, "--json", help="Output results as JSON"),
    data_dir: str = typer.Option("data", "--data-dir", help="Data directory"),
    auto_fetch: bool = typer.Option(True, "--auto-fetch/--no-fetch", help="Auto-fetch missing data"),
):
    """Backtest a strategy against cached historical data.

    Examples:
      hl backtest run -s momentum_breakout -c BTC -d 90
      hl backtest run -s trend_follower -c ETH --interval 4h --days 365
      hl backtest run -s mean_reversion -c SOL --capital 50000 --leverage 5
    """
    _ensure_path()

    from engines.data.candle_cache import CandleCache
    from engines.learning.backtest_engine import BacktestEngine, BacktestConfig
    from engines.learning.backtest_reporter import BacktestReporter

    db_path = f"{data_dir}/candles/candles.db"
    cache = CandleCache(db_path=db_path)

    config = BacktestConfig(
        coin=coin.upper(),
        interval=interval,
        days=days,
        initial_capital=capital,
        max_leverage=leverage,
        fee_bps=fee_bps,
    )

    # Check if we have enough data
    existing = cache.count(coin, interval)
    if existing == 0 and auto_fetch:
        typer.echo(f"\n  No cached data for {coin.upper()} {interval}. Fetching {days} days...")
        from engines.data.data_fetcher import DataFetcher
        import time, os
        os.environ.setdefault("HL_TESTNET", "false")
        from hyperliquid.info import Info
        from hyperliquid.utils.constants import MAINNET_API_URL
        info = Info(base_url=MAINNET_API_URL, skip_ws=True)

        class _Proxy:
            def __init__(self, i): self._info = i

        fetcher = DataFetcher(cache=cache, proxy=_Proxy(info))
        fetcher.backfill(coin, interval, days)
        typer.echo(f"  Fetched {cache.count(coin, interval):,} candles.\n")
    elif existing == 0:
        typer.echo(f"\n  No data for {coin.upper()} {interval}. Run: hl data fetch --coin {coin} --interval {interval}\n")
        cache.close()
        raise typer.Exit(1)

    # Load strategy
    strategy_instance = _load_strategy(strategy)
    if strategy_instance is None:
        typer.echo(f"\n  Unknown strategy: '{strategy}'")
        typer.echo("  Available: momentum_breakout, trend_follower, mean_reversion, grid, scalper,")
        typer.echo("            avellaneda_mm, power_law_btc, bollinger_reversion, vwap_twap,")
        typer.echo("            funding_arb, orderflow, rsi_contrarian, breakout_pullback,")
        typer.echo("            macd_trend, pair_spread")
        typer.echo("")
        cache.close()
        raise typer.Exit(1)

    # Run backtest
    engine = BacktestEngine(cache, config)
    result = engine.run(strategy_instance)

    # Output
    if json_output:
        print(BacktestReporter.to_json(result))
    else:
        BacktestReporter.print_summary(result)
        if chart and result.equity_curve:
            chart_path = f"{data_dir}/backtest/{coin.lower()}_{interval}_{strategy}.png"
            saved = BacktestReporter.plot_equity(result, chart_path)
            if saved:
                typer.echo(f"  Chart saved: {saved}\n")

    cache.close()


def _load_strategy(name: str):
    """Load a strategy by name from the registry."""
    try:
        from cli.strategy_registry import resolve_strategy_path, STRATEGY_REGISTRY
        if name not in STRATEGY_REGISTRY:
            return None

        path = resolve_strategy_path(name)
        module_path, class_name = path.split(":")
        import importlib
        mod = importlib.import_module(module_path)
        cls = getattr(mod, class_name)
        return cls()
    except Exception as exc:
        log_msg = f"Failed to load strategy '{name}': {exc}"
        try:
            import logging
            logging.getLogger("backtest").debug(log_msg)
        except Exception:
            pass
        return None
