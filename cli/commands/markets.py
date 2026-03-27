"""hl markets — browse, search, and filter all Hyperliquid perpetual contracts."""
from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import List, Optional

import typer

markets_app = typer.Typer(no_args_is_help=False)


def _get_proxy(mainnet: bool):
    """Build a DirectHLProxy or DirectMockProxy depending on config."""
    project_root = str(Path(__file__).resolve().parent.parent.parent)
    if project_root not in sys.path:
        sys.path.insert(0, project_root)

    mock = os.environ.get("HL_MOCK", "false").lower() == "true"
    if mock:
        from cli.hl_adapter import DirectMockProxy
        return DirectMockProxy()

    from cli.config import TradingConfig
    from parent.hl_proxy import HLProxy

    cfg = TradingConfig()
    try:
        key = cfg.get_private_key()
    except RuntimeError:
        key = ""

    testnet = not mainnet and os.environ.get("HL_TESTNET", "true").lower() == "true"
    hl = HLProxy(private_key=key, testnet=testnet)
    from cli.hl_adapter import DirectHLProxy
    return DirectHLProxy(hl)


def _format_volume(v: float) -> str:
    """Human-readable volume string."""
    if v >= 1e9:
        return f"${v / 1e9:.2f}B"
    if v >= 1e6:
        return f"${v / 1e6:.1f}M"
    if v >= 1e3:
        return f"${v / 1e3:.0f}K"
    return f"${v:.0f}"


def _format_oi(oi: float, price: float) -> str:
    """OI in notional USD."""
    notional = oi * price
    return _format_volume(notional)


def _format_funding(rate: float) -> str:
    """Annualized funding rate as percentage."""
    annual = rate * 8760 * 100  # hourly -> annual %
    sign = "+" if annual > 0 else ""
    return f"{sign}{annual:.1f}%"


@markets_app.callback(invoke_without_command=True)
def markets_list(
    ctx: typer.Context,
    search: Optional[str] = typer.Option(None, "--search", "-s", help="Search by coin name (case-insensitive)"),
    sort_by: str = typer.Option("volume", "--sort", help="Sort by: volume, oi, name, leverage, funding, price"),
    min_volume: float = typer.Option(0, "--min-volume", help="Min 24h volume in USD"),
    min_oi: float = typer.Option(0, "--min-oi", help="Min open interest (notional USD)"),
    max_leverage: Optional[int] = typer.Option(None, "--max-leverage", help="Filter by max leverage >= N"),
    limit: int = typer.Option(50, "--limit", "-n", help="Max rows to display"),
    mainnet: bool = typer.Option(False, "--mainnet", help="Query mainnet instead of testnet"),
    json_out: bool = typer.Option(False, "--json", help="Output as JSON"),
):
    """List all Hyperliquid perpetual contracts with live market data.

    Examples:
        hl markets                          # Top 50 by volume
        hl markets -s BTC                   # Search for BTC
        hl markets --sort oi --limit 20     # Top 20 by open interest
        hl markets --min-volume 100000000   # Volume > $100M
        hl markets --max-leverage 40        # Coins with 40x+ leverage
    """
    if ctx.invoked_subcommand is not None:
        return

    proxy = _get_proxy(mainnet)

    try:
        data = proxy.get_all_markets()
    except Exception as e:
        typer.echo(f"ERROR: Failed to fetch markets: {e}", err=True)
        raise typer.Exit(1)

    if not data or len(data) < 2:
        typer.echo("ERROR: Unexpected response from HL API", err=True)
        raise typer.Exit(1)

    universe = data[0].get("universe", [])
    ctxs = data[1] if len(data) > 1 else []

    # Merge universe metadata with live asset contexts
    markets = []
    for i, asset in enumerate(universe):
        ctx_data = ctxs[i] if i < len(ctxs) else {}
        name = asset.get("name", "")
        mark_px = float(ctx_data.get("markPx", 0))
        oi_base = float(ctx_data.get("openInterest", 0))
        volume = float(ctx_data.get("dayNtlVlm", 0))
        funding = float(ctx_data.get("funding", 0))
        oracle_px = float(ctx_data.get("oraclePx", 0))
        oi_notional = oi_base * mark_px if mark_px > 0 else 0

        markets.append({
            "name": name,
            "instrument": f"{name}-PERP",
            "sz_decimals": asset.get("szDecimals", 0),
            "max_leverage": asset.get("maxLeverage", 0),
            "mark_price": mark_px,
            "oracle_price": oracle_px,
            "volume_24h": volume,
            "open_interest_base": oi_base,
            "open_interest_notional": oi_notional,
            "funding_rate": funding,
            "prev_day_price": float(ctx_data.get("prevDayPx", 0)),
            "premium": float(ctx_data.get("premium", 0)),
            "only_isolated": asset.get("onlyIsolated", False),
        })

    # --- Filters ---
    if search:
        q = search.upper()
        markets = [m for m in markets if q in m["name"].upper()]

    if min_volume > 0:
        markets = [m for m in markets if m["volume_24h"] >= min_volume]

    if min_oi > 0:
        markets = [m for m in markets if m["open_interest_notional"] >= min_oi]

    if max_leverage is not None:
        markets = [m for m in markets if m["max_leverage"] >= max_leverage]

    # --- Sort ---
    sort_keys = {
        "volume": lambda m: m["volume_24h"],
        "oi": lambda m: m["open_interest_notional"],
        "name": lambda m: m["name"],
        "leverage": lambda m: m["max_leverage"],
        "funding": lambda m: abs(m["funding_rate"]),
        "price": lambda m: m["mark_price"],
    }
    key_fn = sort_keys.get(sort_by, sort_keys["volume"])
    reverse = sort_by != "name"
    markets.sort(key=key_fn, reverse=reverse)

    # --- Limit ---
    markets = markets[:limit]

    if not markets:
        typer.echo("No markets match your filters.")
        return

    # --- Output ---
    if json_out:
        import json
        typer.echo(json.dumps(markets, indent=2))
        return

    # Table output
    network = "mainnet" if mainnet else "testnet"
    typer.echo(f"Hyperliquid Perpetual Contracts ({network}) — {len(markets)} shown\n")

    # Header
    header = f"{'#':>3}  {'Coin':<10} {'Instrument':<14} {'Price':>12} {'24h Volume':>12} {'OI (Notional)':>14} {'Funding (Ann)':>14} {'Max Lev':>8}"
    typer.echo(header)
    typer.echo("-" * len(header))

    for i, m in enumerate(markets, 1):
        price_str = f"${m['mark_price']:,.2f}" if m['mark_price'] >= 1 else f"${m['mark_price']:.6f}"
        row = (
            f"{i:>3}  "
            f"{m['name']:<10} "
            f"{m['instrument']:<14} "
            f"{price_str:>12} "
            f"{_format_volume(m['volume_24h']):>12} "
            f"{_format_oi(m['open_interest_base'], m['mark_price']):>14} "
            f"{_format_funding(m['funding_rate']):>14} "
            f"{m['max_leverage']:>7}x"
        )
        typer.echo(row)

    typer.echo(f"\nTotal contracts available: {len(universe)}")
    typer.echo("Use --search, --sort, --min-volume, --min-oi, --max-leverage to filter.")


@markets_app.command("info")
def market_info(
    coin: str = typer.Argument(..., help="Coin name (e.g., BTC, ETH, SOL)"),
    mainnet: bool = typer.Option(False, "--mainnet"),
):
    """Show detailed info for a single contract.

    Examples:
        hl markets info BTC
        hl markets info ETH --mainnet
    """
    proxy = _get_proxy(mainnet)
    coin_upper = coin.upper().replace("-PERP", "")

    try:
        data = proxy.get_all_markets()
    except Exception as e:
        typer.echo(f"ERROR: Failed to fetch markets: {e}", err=True)
        raise typer.Exit(1)

    universe = data[0].get("universe", [])
    ctxs = data[1] if len(data) > 1 else []

    found = None
    for i, asset in enumerate(universe):
        if asset.get("name", "").upper() == coin_upper:
            ctx_data = ctxs[i] if i < len(ctxs) else {}
            found = {**asset, **ctx_data, "index": i}
            break

    if not found:
        typer.echo(f"Contract '{coin_upper}' not found.")
        typer.echo(f"Use 'hl markets --search {coin_upper}' to search.")
        raise typer.Exit(1)

    mark_px = float(found.get("markPx", 0))
    oracle_px = float(found.get("oraclePx", 0))
    oi = float(found.get("openInterest", 0))
    volume = float(found.get("dayNtlVlm", 0))
    funding = float(found.get("funding", 0))
    prev_day = float(found.get("prevDayPx", 0))
    premium = float(found.get("premium", 0))

    change_pct = ((mark_px - prev_day) / prev_day * 100) if prev_day > 0 else 0

    network = "mainnet" if mainnet else "testnet"
    typer.echo(f"\n{'=' * 50}")
    typer.echo(f"  {coin_upper}-PERP  ({network})")
    typer.echo(f"{'=' * 50}")
    typer.echo(f"  Mark Price:       ${mark_px:,.2f}")
    typer.echo(f"  Oracle Price:     ${oracle_px:,.2f}")
    typer.echo(f"  24h Change:       {change_pct:+.2f}%")
    typer.echo(f"  Premium:          {premium:.6f}")
    typer.echo(f"  24h Volume:       {_format_volume(volume)}")
    typer.echo(f"  Open Interest:    {oi:,.2f} {coin_upper} ({_format_oi(oi, mark_px)})")
    typer.echo(f"  Funding (hourly): {funding:.8f}")
    typer.echo(f"  Funding (annual): {_format_funding(funding)}")
    typer.echo(f"  Max Leverage:     {found.get('maxLeverage', 'N/A')}x")
    typer.echo(f"  Size Decimals:    {found.get('szDecimals', 'N/A')}")
    typer.echo(f"  Isolated Only:    {found.get('onlyIsolated', False)}")
    typer.echo(f"  Universe Index:   {found.get('index')}")
    typer.echo(f"{'=' * 50}\n")
