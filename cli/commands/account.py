"""hl account — show HL account state."""
from __future__ import annotations

import logging
import sys
from pathlib import Path

import typer


def account_cmd(
    mainnet: bool = typer.Option(
        False, "--mainnet",
        help="Use mainnet (default: testnet)",
    ),
):
    """Show Hyperliquid account state (margin, balance)."""
    project_root = str(Path(__file__).resolve().parent.parent.parent)
    if project_root not in sys.path:
        sys.path.insert(0, project_root)

    logging.basicConfig(level=logging.WARNING)

    from cli.display import account_table
    from common.account_state import fetch_registered_account_state

    if mainnet:
        logging.getLogger(__name__).warning(
            "--mainnet is currently ignored by `hl account`; account resolution is driven by the configured wallets"
        )

    state = fetch_registered_account_state()

    if not state:
        typer.echo("Failed to fetch account state", err=True)
        raise typer.Exit(1)

    typer.echo(account_table(state))
