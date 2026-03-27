"""hl keys — unified key management across backends."""
from __future__ import annotations

import sys
from pathlib import Path

import typer

keys_app = typer.Typer(no_args_is_help=True)


def _ensure_path():
    project_root = str(Path(__file__).resolve().parent.parent.parent)
    if project_root not in sys.path:
        sys.path.insert(0, project_root)


BACKEND_NAMES = ["ows", "keychain", "keystore", "file"]


def _print_key_guide():
    """Print a human-friendly guide for finding your Hyperliquid private key."""
    typer.echo("")
    typer.echo("\033[1m  Hyperliquid Private Key Import\033[0m")
    typer.echo("  " + "-" * 50)
    typer.echo("")
    typer.echo("  Your private key is an EVM wallet key — the same kind")
    typer.echo("  used by MetaMask, Rabby, or any Ethereum wallet.")
    typer.echo("")
    typer.echo("  \033[1mWhat it looks like:\033[0m")
    typer.echo("    64 hex characters (0-9, a-f), optionally starting with 0x")
    typer.echo("    Example: 0x4c0883a69102937d6231471b5dbb6204fe512961...")
    typer.echo("")
    typer.echo("  \033[1mWhere to find it:\033[0m")
    typer.echo("    MetaMask:  Settings > Security > Reveal Private Key")
    typer.echo("    Rabby:     Click address > Export Private Key")
    typer.echo("    Other:     Check your wallet's export/backup settings")
    typer.echo("")
    typer.echo("  \033[1mHyperliquid API wallet:\033[0m")
    typer.echo("    If you use an API-only wallet (created on app.hyperliquid.xyz),")
    typer.echo("    export it from: Portfolio > API Wallets > Export Key")
    typer.echo("")
    typer.echo("  \033[33m  NEVER share this key. Anyone with it controls your funds.\033[0m")
    typer.echo("  \033[33m  This tool encrypts and stores it securely after import.\033[0m")
    typer.echo("")
    typer.echo("  \033[1mWhat happens next:\033[0m")
    typer.echo("    Your key will be encrypted and stored in 3 places:")
    typer.echo("    1. OWS vault       — AES-256-GCM encrypted on disk (bot reads from here)")
    typer.echo("    2. macOS Keychain  — local login keychain (fast backup)")
    typer.echo("    3. iCloud Drive    — encrypted backup file (survives machine death)")
    typer.echo("    The raw key is never stored in plaintext anywhere.")
    typer.echo("")


@keys_app.command("import")
def keys_import(
    backend: str = typer.Option(
        "", "--backend", "-b",
        help="Storage backend (default: OWS + Keychain dual-store). "
             "Options: ows, keychain, keystore, file",
    ),
    quiet: bool = typer.Option(
        False, "--quiet", "-q",
        help="Skip the explanation and just prompt for the key",
    ),
    force: bool = typer.Option(
        False, "--force", "-f",
        help="Archive existing key and store the new one (old key is never deleted)",
    ),
):
    """Import your Hyperliquid wallet private key securely.

    By default, stores in BOTH OWS vault (encrypted) and macOS Keychain
    (iCloud backup). Use --backend to target a specific backend instead.
    """
    _ensure_path()

    if not quiet:
        _print_key_guide()

    private_key = typer.prompt(
        "  Paste your private key (input is hidden)",
        hide_input=True,
    )
    private_key = private_key.strip()

    if not private_key:
        typer.echo("\n  No key entered. Aborting.", err=True)
        raise typer.Exit(1)

    # Normalize
    if not private_key.startswith("0x"):
        private_key = "0x" + private_key

    # Validate length (0x + 64 hex chars = 66)
    stripped = private_key[2:]
    if len(stripped) != 64:
        typer.echo(
            f"\n  Invalid key length: got {len(stripped)} characters, expected 64."
            "\n  A private key is exactly 64 hex characters (0-9, a-f)."
            "\n  Example: 0x4c0883a69102937d6231471b5dbb6204fe512961708279f388e80a09fec1e185",
            err=True,
        )
        raise typer.Exit(1)

    # Validate hex
    try:
        int(stripped, 16)
    except ValueError:
        typer.echo(
            "\n  Invalid characters in key. A private key contains only hex"
            "\n  characters: 0-9 and a-f. Check for accidental spaces or typos.",
            err=True,
        )
        raise typer.Exit(1)

    # Derive address from key
    try:
        from eth_account import Account
        acct = Account.from_key(private_key)
        address = acct.address.lower()
    except Exception as e:
        typer.echo(f"\n  Invalid private key: {e}", err=True)
        raise typer.Exit(1)

    typer.echo(f"\n  Wallet address: \033[1m{address}\033[0m")

    if not backend:
        # Default: dual-store to OWS + Keychain
        from common.credentials import store_key_secure
        try:
            stored_in = store_key_secure(address, private_key, force=force)
            typer.echo("")
            for name in stored_in:
                if name == "ows":
                    typer.echo("  \033[32m✓ OWS vault\033[0m       — encrypted on disk (~/.ows/wallets/)")
                elif name == "keychain":
                    typer.echo("  \033[32m✓ macOS Keychain\033[0m  — local login keychain")
                elif name == "icloud-drive":
                    typer.echo("  \033[32m✓ iCloud Drive\033[0m    — encrypted backup (syncs to cloud)")
            typer.echo("")
            if "icloud-drive" not in stored_in:
                typer.echo("  \033[33m⚠ iCloud Drive backup failed — enable iCloud Drive in System Settings\033[0m")
                typer.echo("    Your key is stored locally but NOT backed up to the cloud.")
                typer.echo("")
            typer.echo("  Verify with: hl keys list")
            typer.echo("")
        except ValueError as e:
            # Overwrite protection triggered
            typer.echo(f"\n  \033[33mKey already exists:\033[0m {e}", err=True)
            typer.echo("")
            typer.echo("  To replace it (old key is archived, never deleted):")
            typer.echo("    hl keys import --force")
            typer.echo("")
            raise typer.Exit(1)
        except Exception as e:
            typer.echo(f"\n  Failed to store key: {e}", err=True)
            raise typer.Exit(1)
    else:
        # Specific backend requested
        if backend not in BACKEND_NAMES:
            typer.echo(f"\n  Unknown backend '{backend}'. Choose from: {', '.join(BACKEND_NAMES)}", err=True)
            raise typer.Exit(1)

        from common.credentials import get_backend

        be = get_backend(backend)
        if be is None or not be.available():
            typer.echo(f"\n  Backend '{backend}' is not available on this system.", err=True)
            raise typer.Exit(1)

        try:
            be.store_key(address, private_key)
            typer.echo(f"\n  Key stored for {address} via {backend} backend.")
        except Exception as e:
            typer.echo(f"\n  Failed to store key: {e}", err=True)
            raise typer.Exit(1)


@keys_app.command("list")
def keys_list():
    """List all keys across all available backends."""
    _ensure_path()

    from common.credentials import get_all_backends

    found_any = False
    typer.echo(f"{'Address':<44} {'Backend'}")
    typer.echo("-" * 60)

    for be in get_all_backends():
        if not be.available():
            continue
        try:
            addresses = be.list_keys()
            for addr in addresses:
                typer.echo(f"{addr:<44} {be.name()}")
                found_any = True
        except Exception:
            pass

    if not found_any:
        typer.echo("No keys found across any backend.")
        typer.echo("Import one with: hl keys import --backend keychain")


@keys_app.command("migrate")
def keys_migrate(
    from_backend: str = typer.Option(..., "--from", help="Source backend name"),
    to_backend: str = typer.Option(..., "--to", help="Destination backend name"),
    address: str = typer.Option("", "--address", "-a", help="Specific address to migrate (default: all)"),
):
    """Copy keys from one backend to another."""
    _ensure_path()

    from common.credentials import get_backend

    src = get_backend(from_backend)
    dst = get_backend(to_backend)

    if src is None or not src.available():
        typer.echo(f"Source backend '{from_backend}' not available.", err=True)
        raise typer.Exit(1)
    if dst is None or not dst.available():
        typer.echo(f"Destination backend '{to_backend}' not available.", err=True)
        raise typer.Exit(1)

    if address:
        addresses = [address.lower()]
    else:
        addresses = src.list_keys()

    if not addresses:
        typer.echo(f"No keys found in '{from_backend}' backend.")
        raise typer.Exit()

    migrated = 0
    for addr in addresses:
        try:
            key = src.get_key(addr)
            if key is None:
                typer.echo(f"  SKIP  {addr} — key not retrievable from {from_backend}")
                continue
            dst.store_key(addr, key)
            typer.echo(f"  OK    {addr} -> {to_backend}")
            migrated += 1
        except NotImplementedError as e:
            typer.echo(f"  FAIL  {addr} — {e}", err=True)
        except Exception as e:
            typer.echo(f"  FAIL  {addr} — {e}", err=True)

    typer.echo(f"\nMigrated {migrated}/{len(addresses)} key(s) from {from_backend} to {to_backend}.")


@keys_app.command("backup-status")
def keys_backup_status():
    """Check the status of iCloud Drive encrypted backups."""
    _ensure_path()

    from common.credentials import _BACKUP_DIR, _ICLOUD_DRIVE

    typer.echo("")
    # Check iCloud Drive
    if _ICLOUD_DRIVE.exists():
        typer.echo("  \033[32m✓ iCloud Drive\033[0m  — available")
    else:
        typer.echo("  \033[31m✗ iCloud Drive\033[0m  — not found")
        typer.echo("    Enable iCloud Drive in System Settings > Apple ID > iCloud > iCloud Drive")
        typer.echo("")
        raise typer.Exit(1)

    # Check backup directory
    if _BACKUP_DIR.exists():
        backups = list(_BACKUP_DIR.glob("*.enc"))
        if backups:
            typer.echo(f"  \033[32m✓ Backups\033[0m       — {len(backups)} encrypted backup(s) found")
            typer.echo("")
            for bf in backups:
                import json as _json
                try:
                    data = _json.loads(bf.read_text())
                    addr = data.get("address", "unknown")
                    created = data.get("created", "unknown")
                    typer.echo(f"    {addr}  created: {created}")
                except Exception:
                    typer.echo(f"    {bf.name}  (could not read)")
        else:
            typer.echo("  \033[33m⚠ Backups\033[0m       — backup directory exists but no backups found")
    else:
        typer.echo("  \033[33m⚠ Backups\033[0m       — no backup directory yet (run: hl keys import)")

    typer.echo("")
    typer.echo("  Backup location: ~/Library/Mobile Documents/com~apple~CloudDocs/agent-cli-backup/")
    typer.echo("  These files sync to iCloud automatically and are encrypted.")
    typer.echo("")


@keys_app.command("restore")
def keys_restore(
    address: str = typer.Argument(..., help="Wallet address to restore (0x...)"),
):
    """Restore a key from iCloud Drive encrypted backup.

    Use this on a new Mac after signing into your Apple ID.
    The backup must have been created on a Mac with the same hardware UUID.
    """
    _ensure_path()

    from common.credentials import icloud_restore, store_key_secure

    address = address.lower()
    if not address.startswith("0x"):
        address = "0x" + address

    typer.echo(f"\n  Restoring key for {address}...")

    key = icloud_restore(address)
    if key is None:
        typer.echo("  \033[31m✗ No backup found\033[0m for this address.", err=True)
        typer.echo("    Check: hl keys backup-status")
        typer.echo("")
        raise typer.Exit(1)

    # Validate the restored key
    try:
        from eth_account import Account
        acct = Account.from_key(key)
        if acct.address.lower() != address:
            typer.echo(f"  \033[31m✗ Key mismatch\033[0m — decrypted key produces {acct.address.lower()}, not {address}", err=True)
            typer.echo("    This may mean the backup was created on a different machine.")
            raise typer.Exit(1)
    except Exception as e:
        typer.echo(f"  \033[31m✗ Invalid key\033[0m — {e}", err=True)
        raise typer.Exit(1)

    # Store in all backends
    stored_in = store_key_secure(address, key, force=True)
    typer.echo(f"  \033[32m✓ Key restored\033[0m and stored in: {', '.join(stored_in)}")
    typer.echo("")
