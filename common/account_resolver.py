"""Account resolver — single source of truth for wallet addresses.

Replaces the pattern of hardcoding addresses like:
    MAIN_ACCOUNT = "0x80B5801ce295C4D469F4C0C2e7E17bd84dF0F205"
    VAULT_ADDRESS = "0x9da9a9aef5a968277b5ea66c6a0df7add49d98da"

...in every file, which is fragile (multi-user, multi-account systems break)
and leaks real addresses into the codebase.

Resolution order for each address type:
  1. Environment variable (HL_MAIN_WALLET, HL_VAULT_ADDRESS, HL_SECONDARY_WALLET)
  2. Wallet file (~/.hl-agent/wallets.json or equivalent)
  3. Raise a clear error with instructions

For the OpenClaw agent:
  - "main" account  → HL_MAIN_WALLET env var
  - "vault" account → HL_VAULT_ADDRESS env var (optional, may not exist for all users)
  - "sub" accounts  → HL_SUB_WALLET_n env vars (n=1,2,3...)

New users just set HL_MAIN_WALLET in their .env and everything works.
Your setup: two accounts (main + vault) both supported automatically.
"""
from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Dict, List, Optional

log = logging.getLogger("account_resolver")

# Environment variable names
ENV_MAIN_WALLET    = "HL_MAIN_WALLET"
ENV_VAULT_ADDRESS  = "HL_VAULT_ADDRESS"
ENV_SUB_PREFIX     = "HL_SUB_WALLET_"   # HL_SUB_WALLET_1, HL_SUB_WALLET_2, ...

# Wallet file location (optional, for non-env setups)
WALLET_FILE = Path.home() / ".hl-agent" / "wallets.json"


def resolve_main_wallet(required: bool = True) -> Optional[str]:
    """Return the main trading wallet address.

    Args:
        required: If True, raises RuntimeError when not found.

    Returns:
        Wallet address string (0x-prefixed) or None if not found and not required.
    """
    addr = os.environ.get(ENV_MAIN_WALLET)
    if addr:
        return addr.strip()

    # Try wallet file
    addr = _load_from_wallet_file("main")
    if addr:
        return addr

    if required:
        raise RuntimeError(
            f"No main wallet configured. Set {ENV_MAIN_WALLET} environment variable.\n"
            f"  Example: export {ENV_MAIN_WALLET}=0xYourWalletAddress\n"
            f"  Or add it to your .env file."
        )
    return None


def resolve_vault_address(required: bool = False) -> Optional[str]:
    """Return the vault wallet address, if configured.

    Vaults are optional — not all users have one.

    Args:
        required: If True, raises RuntimeError when not found.

    Returns:
        Vault address string or None.
    """
    addr = os.environ.get(ENV_VAULT_ADDRESS)
    if addr:
        return addr.strip()

    # Try wallet file
    addr = _load_from_wallet_file("vault")
    if addr:
        return addr

    if required:
        raise RuntimeError(
            f"No vault address configured. Set {ENV_VAULT_ADDRESS} environment variable."
        )

    log.debug("No vault address configured — vault monitoring disabled")
    return None


def resolve_sub_wallets() -> List[str]:
    """Return all configured sub-wallet addresses.

    Returns:
        List of 0x-prefixed address strings (may be empty).
    """
    subs = []
    i = 1
    while True:
        addr = os.environ.get(f"{ENV_SUB_PREFIX}{i}")
        if not addr:
            break
        subs.append(addr.strip())
        i += 1

    # Also check wallet file
    file_subs = _load_subs_from_wallet_file()
    for s in file_subs:
        if s not in subs:
            subs.append(s)

    if subs:
        log.debug("Resolved %d sub-wallet(s)", len(subs))
    return subs


def resolve_all_accounts() -> Dict[str, Optional[str]]:
    """Return a dict of all configured account addresses.

    Returns:
        Dict with keys: "main", "vault", "subs"
    """
    main = resolve_main_wallet(required=False)
    vault = resolve_vault_address(required=False)
    subs = resolve_sub_wallets()
    return {
        "main": main,
        "vault": vault,
        "subs": subs,
        "all_addresses": [a for a in [main, vault] + subs if a],
    }


def _load_from_wallet_file(account_type: str) -> Optional[str]:
    """Try to load an address from the wallet JSON file."""
    if not WALLET_FILE.exists():
        return None
    try:
        import json
        data = json.loads(WALLET_FILE.read_text())
        return data.get(account_type)
    except Exception as e:
        log.debug("Could not read wallet file: %s", e)
        return None


def _load_subs_from_wallet_file() -> List[str]:
    """Load sub-wallet list from wallet JSON file."""
    if not WALLET_FILE.exists():
        return []
    try:
        import json
        data = json.loads(WALLET_FILE.read_text())
        subs = data.get("subs", [])
        return subs if isinstance(subs, list) else []
    except Exception:
        return []
