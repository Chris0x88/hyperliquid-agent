"""hl setup — environment validation and initialization."""
from __future__ import annotations

import os
import sys
from pathlib import Path

import typer

setup_app = typer.Typer(no_args_is_help=True)


@setup_app.command("check")
def setup_check():
    """Validate environment: SDK, keys, builder fee config."""
    project_root = str(Path(__file__).resolve().parent.parent.parent)
    if project_root not in sys.path:
        sys.path.insert(0, project_root)

    issues = []
    ok_items = []

    # 1. Python + hyperliquid SDK
    try:
        import hyperliquid  # noqa: F401
        ok_items.append("hyperliquid-python-sdk installed")
    except ImportError:
        issues.append("hyperliquid-python-sdk not installed (pip install hyperliquid-python-sdk)")

    # 2. Private key
    has_env_key = bool(os.environ.get("HL_PRIVATE_KEY"))
    from cli.keystore import list_keystores
    has_keystore = len(list_keystores()) > 0
    if has_env_key:
        ok_items.append("HL_PRIVATE_KEY set")
    elif has_keystore:
        ok_items.append(f"Keystore found ({len(list_keystores())} keys)")
        if not os.environ.get("HL_KEYSTORE_PASSWORD"):
            issues.append("HL_KEYSTORE_PASSWORD not set (needed for auto-unlock)")
    else:
        issues.append("No private key: set HL_PRIVATE_KEY or run 'hl wallet import'")

    # 3. Network
    testnet = os.environ.get("HL_TESTNET", "true").lower()
    ok_items.append(f"Network: {'testnet' if testnet == 'true' else 'mainnet'}")

    # 4. Builder fee
    from cli.config import TradingConfig
    cfg = TradingConfig()
    bcfg = cfg.get_builder_config()
    if bcfg.enabled:
        ok_items.append(f"Builder fee: {bcfg.fee_bps} bps -> {bcfg.builder_address[:10]}...")
    else:
        ok_items.append("Builder fee: not configured (optional)")

    # 5. LLM key (for claude_agent)
    if os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("GEMINI_API_KEY"):
        ok_items.append("LLM API key found")
    else:
        ok_items.append("LLM API key: not set (only needed for claude_agent strategy)")

    # 6. Data directories
    data_dir = Path("data/cli")
    if data_dir.exists():
        ok_items.append(f"Data dir: {data_dir} exists")
    else:
        ok_items.append(f"Data dir: {data_dir} (will be created on first run)")

    # Report
    typer.echo("Environment Check")
    typer.echo("=" * 40)

    for item in ok_items:
        typer.echo(f"  OK  {item}")

    if issues:
        typer.echo("")
        for issue in issues:
            typer.echo(f"  !!  {issue}")
        typer.echo(f"\n{len(issues)} issue(s) found.")
    else:
        typer.echo("\nAll checks passed.")
