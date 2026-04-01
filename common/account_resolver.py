"""Account resolver — single source of truth for wallet addresses.

Wallet addresses (public, non-secret) live in ~/.hl-agent/wallets.json.
This file is written ONLY by CLI commands (hl wallet register, hl wallet set-vault).
Users never open or edit this file directly.

Storage structure (wallets.json):
  {
    "main": "0xABC...123",             — primary trading account
    "vault": "0xDEF...456",            — optional vault (not all users have one)
    "subs": ["0xGHI...789"],           — optional sub-accounts (any number)
    "labels": {"0xABC...123": "Main"} — optional human labels
  }

For private KEYS (not addresses), the system uses OWS vault + macOS Keychain
via common/credentials.py and cli/keystore.py. This module handles addresses only.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Dict, List, Optional

log = logging.getLogger("account_resolver")

WALLET_FILE = Path.home() / ".hl-agent" / "wallets.json"


# ── Read-only resolution (used by all runtime code) ──────────────────────────

def resolve_main_wallet(required: bool = True) -> Optional[str]:
    """Return the main trading wallet address.

    Reads from ~/.hl-agent/wallets.json (written by 'hl wallet register').

    Args:
        required: If True, raises RuntimeError when not found.
    """
    data = _load_wallet_file()
    addr = data.get("main")
    if addr:
        return addr

    if required:
        raise RuntimeError(
            "No main wallet registered.\n"
            "  Run:  hl wallet register\n"
            "  It will detect your wallet from your private key automatically."
        )
    return None


def resolve_vault_address(required: bool = False) -> Optional[str]:
    """Return the vault wallet address, if configured.

    Vaults are optional — not all users have one. If not configured, returns None.

    Args:
        required: If True, raises RuntimeError when not found.
    """
    data = _load_wallet_file()
    addr = data.get("vault")
    if addr:
        return addr

    if required:
        raise RuntimeError(
            "No vault address configured.\n"
            "  Run:  hl wallet set-vault 0xYourVaultAddress"
        )

    log.debug("No vault address in wallets.json — vault monitoring disabled")
    return None


def resolve_sub_wallets() -> List[str]:
    """Return all configured sub-wallet addresses (may be empty)."""
    data = _load_wallet_file()
    subs = data.get("subs", [])
    return subs if isinstance(subs, list) else []


def resolve_all_accounts() -> Dict:
    """Return a full dict of all registered wallet addresses."""
    data = _load_wallet_file()
    main = data.get("main")
    vault = data.get("vault")
    subs = data.get("subs", [])
    labels = data.get("labels", {})
    return {
        "main": main,
        "vault": vault,
        "subs": subs,
        "labels": labels,
        "all_addresses": [a for a in [main, vault] + subs if a],
    }


def get_label(address: str) -> str:
    """Return the human label for an address, or a short-form fallback."""
    data = _load_wallet_file()
    labels = data.get("labels", {})
    return labels.get(address.lower(), address[:6] + "..." + address[-4:])


# ── Write operations (used only by CLI setup commands) ────────────────────────

def register_main_wallet(address: str, label: str = "Main") -> None:
    """Register the main wallet address. Called by 'hl wallet register'."""
    _write_wallet({"main": address.lower(), "labels": {address.lower(): label}})
    log.info("Registered main wallet: %s (%s)", address, label)


def register_vault(address: str, label: str = "Vault") -> None:
    """Register a vault address. Called by 'hl wallet set-vault'."""
    _write_wallet({"vault": address.lower(), "labels": {address.lower(): label}})
    log.info("Registered vault: %s (%s)", address, label)


def register_sub_wallet(address: str, label: Optional[str] = None) -> None:
    """Add a sub-account address. Called by 'hl wallet add-sub'."""
    data = _load_wallet_file()
    subs = data.get("subs", [])
    addr = address.lower()
    if addr not in subs:
        subs.append(addr)
    data["subs"] = subs
    if label:
        data.setdefault("labels", {})[addr] = label
    _save_wallet_file(data)
    log.info("Registered sub-wallet: %s (%s)", address, label or "")


def remove_address(address: str) -> bool:
    """Remove an address from all slots. Returns True if found and removed."""
    data = _load_wallet_file()
    addr = address.lower()
    changed = False

    if data.get("main") == addr:
        del data["main"]
        changed = True
    if data.get("vault") == addr:
        del data["vault"]
        changed = True
    subs = data.get("subs", [])
    if addr in subs:
        data["subs"] = [s for s in subs if s != addr]
        changed = True
    data.get("labels", {}).pop(addr, None)

    if changed:
        _save_wallet_file(data)
    return changed


# ── Internal helpers ──────────────────────────────────────────────────────────

def _load_wallet_file() -> dict:
    """Load wallets.json, returning empty dict if not found or corrupt."""
    if not WALLET_FILE.exists():
        return {}
    try:
        return json.loads(WALLET_FILE.read_text())
    except Exception as e:
        log.warning("Could not read wallets.json: %s", e)
        return {}


def _write_wallet(updates: dict) -> None:
    """Merge updates into wallets.json atomically."""
    data = _load_wallet_file()
    # Deep merge labels
    if "labels" in updates:
        data.setdefault("labels", {}).update(updates.pop("labels"))
    data.update(updates)
    _save_wallet_file(data)


def _save_wallet_file(data: dict) -> None:
    """Write wallets.json with restricted permissions (owner-read only)."""
    WALLET_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = WALLET_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2))
    tmp.chmod(0o600)
    tmp.rename(WALLET_FILE)

