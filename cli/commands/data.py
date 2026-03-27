"""hl data — fetch, cache, and manage historical market data."""
from __future__ import annotations

import sys
import time
from pathlib import Path

import typer

data_app = typer.Typer(no_args_is_help=True)


def _ensure_path():
    project_root = str(Path(__file__).resolve().parent.parent.parent)
    if project_root not in sys.path:
        sys.path.insert(0, project_root)


@data_app.command("fetch")
def data_fetch(
    coin: str = typer.Option("BTC", "--coin", "-c", help="Coin symbol (BTC, ETH, SOL, etc.)"),
    interval: str = typer.Option("1h", "--interval", "-i", help="Candle interval (1m, 5m, 15m, 1h, 4h, 1d)"),
    days: int = typer.Option(90, "--days", "-d", help="Number of days to fetch"),
    mainnet: bool = typer.Option(True, "--mainnet/--testnet", help="Use mainnet (default) or testnet"),
    data_dir: str = typer.Option("data", "--data-dir", help="Data directory"),
):
    """Fetch historical candles from Hyperliquid API and cache locally.

    Examples:
      hl data fetch --coin BTC --interval 1h --days 90
      hl data fetch --coin ETH --interval 4h --days 365
      hl data fetch --coin SOL --interval 15m --days 30
    """
    _ensure_path()

    from modules.candle_cache import CandleCache
    from modules.data_fetcher import DataFetcher

    db_path = f"{data_dir}/candles/candles.db"
    cache = CandleCache(db_path=db_path)

    # Build a lightweight proxy just for candle fetching
    proxy = _build_proxy(mainnet, testnet=not mainnet)

    fetcher = DataFetcher(cache=cache, proxy=proxy)

    typer.echo(f"\n  Fetching {days} days of {coin.upper()} {interval} candles...")
    typer.echo(f"  Source: Hyperliquid {'mainnet' if mainnet else 'testnet'} API")
    typer.echo("")

    start = time.time()
    count = fetcher.backfill(coin, interval, days)
    elapsed = time.time() - start

    typer.echo(f"  Stored {count:,} new candles in {elapsed:.1f}s")

    # Show cache stats for this coin
    rng = cache.date_range(coin, interval)
    total = cache.count(coin, interval)
    if rng:
        from datetime import datetime
        start_dt = datetime.fromtimestamp(rng[0] / 1000).strftime("%Y-%m-%d %H:%M")
        end_dt = datetime.fromtimestamp(rng[1] / 1000).strftime("%Y-%m-%d %H:%M")
        typer.echo(f"  Cache: {total:,} candles from {start_dt} to {end_dt}")

    typer.echo(f"  DB: {db_path}")
    typer.echo("")
    cache.close()


@data_app.command("stats")
def data_stats(
    data_dir: str = typer.Option("data", "--data-dir", help="Data directory"),
):
    """Show cache statistics — what data is stored locally."""
    _ensure_path()

    from modules.candle_cache import CandleCache
    from datetime import datetime

    db_path = f"{data_dir}/candles/candles.db"
    if not Path(db_path).exists():
        typer.echo("\n  No candle cache found. Run: hl data fetch --coin BTC\n")
        raise typer.Exit()

    cache = CandleCache(db_path=db_path)
    stats = cache.stats()

    typer.echo(f"\n  Candle Cache: {stats['total_candles']:,} total candles")
    typer.echo(f"  DB: {db_path}")
    typer.echo(f"  {'─'*60}")

    for coin, intervals in stats["coins"].items():
        for interval, info in intervals.items():
            start = datetime.fromtimestamp(info["start"] / 1000).strftime("%Y-%m-%d") if info["start"] else "?"
            end = datetime.fromtimestamp(info["end"] / 1000).strftime("%Y-%m-%d") if info["end"] else "?"
            typer.echo(f"  {coin:<6} {interval:<4} {info['count']:>8,} candles  {start} → {end}")

    typer.echo("")
    cache.close()


@data_app.command("export")
def data_export(
    coin: str = typer.Option(..., "--coin", "-c", help="Coin to export"),
    interval: str = typer.Option("1h", "--interval", "-i", help="Interval to export"),
    output: str = typer.Option("", "--output", "-o", help="Output CSV path (default: data/export/{coin}_{interval}.csv)"),
    data_dir: str = typer.Option("data", "--data-dir", help="Data directory"),
):
    """Export cached candles to CSV for external tools."""
    _ensure_path()

    from modules.candle_cache import CandleCache

    db_path = f"{data_dir}/candles/candles.db"
    cache = CandleCache(db_path=db_path)

    if not output:
        output = f"{data_dir}/export/{coin.upper()}_{interval}.csv"

    count = cache.export_csv(coin, interval, output)
    if count:
        typer.echo(f"\n  Exported {count:,} candles to {output}\n")
    else:
        typer.echo(f"\n  No data found for {coin.upper()} {interval}. Run: hl data fetch --coin {coin}\n")

    cache.close()


def _build_proxy(mainnet: bool, testnet: bool):
    """Build a minimal proxy for data fetching (read-only, no private key needed)."""
    import os
    os.environ.setdefault("HL_TESTNET", "false" if mainnet else "true")

    from hyperliquid.info import Info
    from hyperliquid.utils.constants import MAINNET_API_URL, TESTNET_API_URL

    base_url = MAINNET_API_URL if mainnet else TESTNET_API_URL
    info = Info(base_url=base_url, skip_ws=True)

    # Return a simple object with get_candles and _info for the fetcher
    class ReadOnlyProxy:
        def __init__(self, info_obj):
            self._info = info_obj

        def get_candles(self, coin, interval, lookback_ms):
            end = int(time.time() * 1000)
            start = end - lookback_ms
            return self._info.candles_snapshot(coin, interval, start, end)

    return ReadOnlyProxy(info)
