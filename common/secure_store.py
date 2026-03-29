"""Encrypted secrets store — AES-256-GCM for arbitrary key-value secrets.

Cross-platform alternative to macOS Keychain for storing Telegram tokens,
API keys, and other non-wallet secrets.

Storage: data/secrets/vault.enc (encrypted JSON)
Key derivation: scrypt from master password
Encryption: AES-256-GCM (same standard as OWS vault)

Usage:
    from common.secure_store import SecretsStore
    store = SecretsStore()
    store.set("telegram_bot_token", "123:abc")
    token = store.get("telegram_bot_token")
    store.list_keys()  # ["telegram_bot_token"]

On macOS: falls back to Keychain if available (preferred).
On Linux/server: uses the encrypted file store.
"""
from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
import subprocess
import sys
from pathlib import Path
from typing import Dict, List, Optional

log = logging.getLogger("secure_store")

SECRETS_DIR = Path("data/secrets")
VAULT_PATH = SECRETS_DIR / "vault.enc"
SALT_PATH = SECRETS_DIR / ".salt"
KEYCHAIN_SERVICE = "hl-agent-telegram"  # legacy compat


def _is_macos() -> bool:
    return sys.platform == "darwin"


def _keychain_get(key: str) -> Optional[str]:
    """Read from macOS Keychain."""
    if not _is_macos():
        return None
    try:
        r = subprocess.run(
            ["security", "find-generic-password", "-s", KEYCHAIN_SERVICE, "-a", key, "-w"],
            capture_output=True, text=True, timeout=5,
        )
        return r.stdout.strip() if r.returncode == 0 else None
    except (subprocess.TimeoutExpired, OSError):
        return None


def _keychain_set(key: str, value: str) -> bool:
    """Write to macOS Keychain."""
    if not _is_macos():
        return False
    try:
        r = subprocess.run(
            ["security", "add-generic-password", "-s", KEYCHAIN_SERVICE, "-a", key, "-w", value, "-U"],
            capture_output=True, text=True, timeout=5,
        )
        return r.returncode == 0
    except (subprocess.TimeoutExpired, OSError):
        return False


class SecretsStore:
    """Encrypted secrets store with Keychain fallback."""

    def __init__(self, password: Optional[str] = None):
        self._password = password or os.environ.get("HL_SECRETS_PASSWORD", "")
        self._cache: Optional[Dict[str, str]] = None

    def get(self, key: str) -> Optional[str]:
        """Get a secret by key. Tries Keychain first, then encrypted store."""
        # Try Keychain first (macOS)
        val = _keychain_get(key)
        if val:
            return val

        # Fall back to encrypted store
        secrets = self._load()
        return secrets.get(key)

    def set(self, key: str, value: str) -> None:
        """Set a secret. Writes to both Keychain (if available) and encrypted store."""
        # Write to Keychain
        if _is_macos():
            _keychain_set(key, value)

        # Write to encrypted store
        secrets = self._load()
        secrets[key] = value
        self._save(secrets)

    def delete(self, key: str) -> None:
        """Delete a secret."""
        secrets = self._load()
        secrets.pop(key, None)
        self._save(secrets)

    def list_keys(self) -> List[str]:
        """List all stored secret keys."""
        return list(self._load().keys())

    def _load(self) -> Dict[str, str]:
        """Load and decrypt the vault."""
        if self._cache is not None:
            return self._cache

        if not VAULT_PATH.exists():
            self._cache = {}
            return self._cache

        if not self._password:
            log.warning("No password set for secrets store. Set HL_SECRETS_PASSWORD env var.")
            self._cache = {}
            return self._cache

        try:
            from cryptography.hazmat.primitives.ciphers.aead import AESGCM

            raw = VAULT_PATH.read_bytes()
            salt = SALT_PATH.read_bytes() if SALT_PATH.exists() else b""

            # Derive key from password
            dk = hashlib.scrypt(
                self._password.encode(), salt=salt, n=2**14, r=8, p=1, dklen=32
            )

            # Split nonce + ciphertext
            nonce = raw[:12]
            ciphertext = raw[12:]

            aesgcm = AESGCM(dk)
            plaintext = aesgcm.decrypt(nonce, ciphertext, None)
            self._cache = json.loads(plaintext)
            return self._cache
        except Exception as e:
            log.error("Failed to decrypt secrets vault: %s", e)
            self._cache = {}
            return self._cache

    def _save(self, secrets: Dict[str, str]) -> None:
        """Encrypt and save the vault."""
        if not self._password:
            log.warning("No password — secrets only saved to Keychain (macOS)")
            self._cache = secrets
            return

        try:
            from cryptography.hazmat.primitives.ciphers.aead import AESGCM

            SECRETS_DIR.mkdir(parents=True, exist_ok=True)

            # Generate or read salt
            if not SALT_PATH.exists():
                salt = os.urandom(16)
                SALT_PATH.write_bytes(salt)
                os.chmod(SALT_PATH, 0o600)
            else:
                salt = SALT_PATH.read_bytes()

            # Derive key
            dk = hashlib.scrypt(
                self._password.encode(), salt=salt, n=2**14, r=8, p=1, dklen=32
            )

            # Encrypt
            nonce = os.urandom(12)
            aesgcm = AESGCM(dk)
            plaintext = json.dumps(secrets).encode()
            ciphertext = aesgcm.encrypt(nonce, plaintext, None)

            VAULT_PATH.write_bytes(nonce + ciphertext)
            os.chmod(VAULT_PATH, 0o600)

            self._cache = secrets
            log.info("Secrets vault saved (%d keys)", len(secrets))
        except ImportError:
            log.warning("cryptography package not installed — secrets only in Keychain")
            self._cache = secrets
        except Exception as e:
            log.error("Failed to save secrets vault: %s", e)
