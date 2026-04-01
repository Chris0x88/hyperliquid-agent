"""hl wallet — encrypted keystore management."""
from __future__ import annotations

import sys
from pathlib import Path

import typer

wallet_app = typer.Typer(no_args_is_help=True)


@wallet_app.command("create")
def wallet_create():
    """Create a new wallet and save encrypted keystore."""
    project_root = str(Path(__file__).resolve().parent.parent.parent)
    if project_root not in sys.path:
        sys.path.insert(0, project_root)

    from eth_account import Account
    from cli.keystore import create_keystore

    account = Account.create()
    typer.echo(f"New address: 0x{account.address[2:].lower()}")
    typer.echo("WARNING: Save your private key somewhere secure before encrypting.")
    typer.echo(f"Private key: {account.key.hex()}")
    typer.echo("")

    password = typer.prompt("Encryption password", hide_input=True)
    password_confirm = typer.prompt("Confirm password", hide_input=True)

    if password != password_confirm:
        typer.echo("Passwords don't match.", err=True)
        raise typer.Exit(1)

    ks_path = create_keystore(account.key.hex(), password)
    typer.echo(f"Keystore saved: {ks_path}")


@wallet_app.command("import")
def wallet_import(
    key: str = typer.Option(..., "--key", "-k", prompt=True, hide_input=True,
                            help="Private key (hex, with or without 0x prefix)"),
):
    """Import an existing private key into encrypted keystore."""
    project_root = str(Path(__file__).resolve().parent.parent.parent)
    if project_root not in sys.path:
        sys.path.insert(0, project_root)

    from cli.keystore import create_keystore

    if not key.startswith("0x"):
        key = "0x" + key

    password = typer.prompt("Encryption password", hide_input=True)
    password_confirm = typer.prompt("Confirm password", hide_input=True)

    if password != password_confirm:
        typer.echo("Passwords don't match.", err=True)
        raise typer.Exit(1)

    try:
        ks_path = create_keystore(key, password)
        typer.echo(f"Keystore saved: {ks_path}")
    except Exception as e:
        typer.echo(f"Failed to create keystore: {e}", err=True)
        raise typer.Exit(1)


@wallet_app.command("list")
def wallet_list():
    """List saved keystores."""
    project_root = str(Path(__file__).resolve().parent.parent.parent)
    if project_root not in sys.path:
        sys.path.insert(0, project_root)

    from cli.keystore import list_keystores

    keystores = list_keystores()

    if not keystores:
        typer.echo("No keystores found. Run 'hl wallet create' or 'hl wallet import'.")
        raise typer.Exit()

    typer.echo(f"{'Address':<44} {'Path'}")
    typer.echo("-" * 80)
    for ks in keystores:
        typer.echo(f"{ks['address']:<44} {ks['path']}")


@wallet_app.command("auto")
def wallet_auto(
    json_output: bool = typer.Option(False, "--json", help="Output as JSON (machine-parseable)"),
    save_env: bool = typer.Option(False, "--save-env", help="Save credentials to ~/.hl-agent/env"),
):
    """Create a new wallet non-interactively (agent-friendly, no prompts)."""
    import json
    import secrets

    project_root = str(Path(__file__).resolve().parent.parent.parent)
    if project_root not in sys.path:
        sys.path.insert(0, project_root)

    from eth_account import Account
    from cli.keystore import create_keystore

    # Generate random password and wallet
    password = secrets.token_urlsafe(32)
    account = Account.create()
    address = account.address

    ks_path = create_keystore(account.key.hex(), password)

    # Auto-save when --json is used (agent path), or when --save-env is explicit
    if json_output:
        save_env = True

    # Optionally persist to ~/.hl-agent/env
    if save_env:
        env_path = Path.home() / ".hl-agent" / "env"
        env_path.parent.mkdir(parents=True, exist_ok=True)
        env_path.write_text(
            f"HL_KEYSTORE_PASSWORD={password}\n"
        )
        env_path.chmod(0o600)

    if json_output:
        result = {
            "address": address,
            "password": password,
            "keystore": str(ks_path),
        }
        if save_env:
            result["env_file"] = str(env_path)
        typer.echo(json.dumps(result))
    else:
        typer.echo(f"Address:  {address}")
        typer.echo(f"Password: {password}")
        typer.echo(f"Keystore: {ks_path}")
        if save_env:
            typer.echo(f"Env file: {env_path}")
        typer.echo("")
        typer.echo("To use this wallet, set:")
        typer.echo(f"  export HL_KEYSTORE_PASSWORD={password}")
        typer.echo("")
        typer.echo("SAVE THE PASSWORD — it cannot be recovered.")


@wallet_app.command("export")
def wallet_export(
    address: str = typer.Option("", "--address", "-a",
                                help="Address to export (default: first keystore)"),
):
    """Export private key from keystore (decrypts with password)."""
    project_root = str(Path(__file__).resolve().parent.parent.parent)
    if project_root not in sys.path:
        sys.path.insert(0, project_root)

    from cli.keystore import list_keystores, load_keystore, _resolve_password

    if not address:
        keystores = list_keystores()
        if not keystores:
            typer.echo("No keystores found.", err=True)
            raise typer.Exit(1)
        address = keystores[0]["address"]

    # Try auto-loading password from env file / env var first
    password = _resolve_password()
    if not password:
        password = typer.prompt("Keystore password", hide_input=True)

    try:
        key = load_keystore(address, password)
        typer.echo(f"Address: {address}")
        typer.echo(f"Private key: {key}")
        typer.echo("")
        typer.echo("Import this key into MetaMask/Rabby to connect your wallet.")
    except FileNotFoundError:
        typer.echo(f"No keystore found for {address}", err=True)
        raise typer.Exit(1)
    except Exception as e:
        typer.echo(f"Decryption failed: {e}", err=True)
        raise typer.Exit(1)


@wallet_app.command("register")
def wallet_register(
    label: str = typer.Option("Main", "--label", "-l", help="Human-readable label for this account"),
):
    """Register your main trading wallet address for monitoring.

    Reads the address from your already-stored private key (no re-entry needed).
    Writes to ~/.hl-agent/wallets.json automatically.

    Run this once after 'hl keys import'.
    """
    project_root = str(Path(__file__).resolve().parent.parent.parent)
    if project_root not in sys.path:
        sys.path.insert(0, project_root)

    from common.credentials import resolve_private_key
    from common.account_resolver import register_main_wallet, resolve_main_wallet

    # Check if already registered
    existing = resolve_main_wallet(required=False)
    if existing:
        typer.echo(f"  Main wallet already registered: {existing}")
        typer.echo("  Use --label to update the label, or run without changes.")
        if not typer.confirm("  Re-register (will overwrite)?", default=False):
            raise typer.Exit(0)

    # Derive address from stored key
    try:
        private_key = resolve_private_key(venue="hl")
    except RuntimeError as e:
        typer.echo(f"\n  No key found: {e}", err=True)
        typer.echo("  Run 'hl keys import' first to store your private key.", err=True)
        raise typer.Exit(1)

    try:
        from eth_account import Account
        acct = Account.from_key(private_key)
        address = acct.address.lower()
    except Exception as e:
        typer.echo(f"\n  Could not derive address from key: {e}", err=True)
        raise typer.Exit(1)

    register_main_wallet(address, label=label)

    typer.echo("")
    typer.echo(f"  \033[32m✓ Registered\033[0m  {address}  ({label})")
    typer.echo(f"             Saved to ~/.hl-agent/wallets.json")
    typer.echo("")
    typer.echo("  If you have a vault account, run:")
    typer.echo("    hl wallet set-vault 0xYourVaultAddress")
    typer.echo("")


@wallet_app.command("set-vault")
def wallet_set_vault(
    address: str = typer.Argument(..., help="Vault account address (0x...)"),
    label: str = typer.Option("Vault", "--label", "-l", help="Human-readable label"),
):
    """Register your vault account address.

    Only needed if you have a HyperLiquid vault. Writes to ~/.hl-agent/wallets.json.
    """
    project_root = str(Path(__file__).resolve().parent.parent.parent)
    if project_root not in sys.path:
        sys.path.insert(0, project_root)

    from common.account_resolver import register_vault

    if not address.startswith("0x") or len(address) != 42:
        typer.echo(f"\n  Invalid address format: {address}", err=True)
        typer.echo("  Expected a 42-character hex address starting with 0x", err=True)
        raise typer.Exit(1)

    register_vault(address.lower(), label=label)

    typer.echo("")
    typer.echo(f"  \033[32m✓ Vault registered\033[0m  {address.lower()}  ({label})")
    typer.echo(f"                   Saved to ~/.hl-agent/wallets.json")
    typer.echo("")


@wallet_app.command("add-sub")
def wallet_add_sub(
    address: str = typer.Argument(..., help="Sub-account address (0x...)"),
    label: str = typer.Option("", "--label", "-l", help="Optional human-readable label"),
):
    """Add a sub-account address for monitoring.

    Supports any number of sub-accounts. Writes to ~/.hl-agent/wallets.json.
    """
    project_root = str(Path(__file__).resolve().parent.parent.parent)
    if project_root not in sys.path:
        sys.path.insert(0, project_root)

    from common.account_resolver import register_sub_wallet

    if not address.startswith("0x") or len(address) != 42:
        typer.echo(f"\n  Invalid address format: {address}", err=True)
        typer.echo("  Expected a 42-character hex address starting with 0x", err=True)
        raise typer.Exit(1)

    register_sub_wallet(address.lower(), label=label or None)

    typer.echo("")
    typer.echo(f"  \033[32m✓ Sub-account added\033[0m  {address.lower()}")
    typer.echo("")


@wallet_app.command("accounts")
def wallet_accounts():
    """Show all registered wallet addresses and their roles.

    Reads from ~/.hl-agent/wallets.json (set up via 'hl wallet register').
    """
    project_root = str(Path(__file__).resolve().parent.parent.parent)
    if project_root not in sys.path:
        sys.path.insert(0, project_root)

    from common.account_resolver import resolve_all_accounts, WALLET_FILE

    if not WALLET_FILE.exists():
        typer.echo("  No wallets registered yet.")
        typer.echo("  Run 'hl wallet register' after importing your key.")
        raise typer.Exit(0)

    accounts = resolve_all_accounts()
    labels = accounts.get("labels", {})

    typer.echo("")
    typer.echo("  Registered Accounts")
    typer.echo("  " + "─" * 50)

    if accounts["main"]:
        lbl = labels.get(accounts["main"], "Main")
        typer.echo(f"  \033[1mMAIN  \033[0m  {accounts['main']}  ({lbl})")
    else:
        typer.echo("  MAIN    (not registered — run 'hl wallet register')")

    if accounts["vault"]:
        lbl = labels.get(accounts["vault"], "Vault")
        typer.echo(f"  VAULT   {accounts['vault']}  ({lbl})")

    for i, sub in enumerate(accounts.get("subs", []), 1):
        lbl = labels.get(sub, f"Sub-{i}")
        typer.echo(f"  SUB {i}   {sub}  ({lbl})")

    typer.echo("")
    typer.echo(f"  Stored at: {WALLET_FILE}")
    typer.echo("")

