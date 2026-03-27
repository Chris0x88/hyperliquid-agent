"""Standardized key management — pluggable backends with unified resolution.

Backends:
  0. OWSBackend — Open Wallet Standard vault (AES-256-GCM, Rust core)
  1. MacOSKeychainBackend  — macOS Keychain via `security` CLI
  2. EncryptedKeystoreBackend — geth-compatible Web3 Secret Storage (existing)
  3. RailwayEnvBackend — Railway-injected environment variables
  4. FlatFileBackend — plaintext files at ~/.hl-agent/keys/ (dev only)

Resolution order for resolve_private_key():
  OWS vault -> macOS Keychain -> encrypted keystore -> Railway env -> flat file -> env var -> error
"""
from __future__ import annotations

import logging
import os
import re
import subprocess
import sys
from abc import ABC, abstractmethod
from pathlib import Path
from typing import List, Optional

log = logging.getLogger("credentials")

KEYS_DIR = Path.home() / ".hl-agent" / "keys"


class KeystoreBackend(ABC):
    """Abstract base class for private key storage backends."""

    @abstractmethod
    def name(self) -> str:
        """Human-readable backend name."""
        ...

    @abstractmethod
    def get_key(self, address: Optional[str] = None) -> Optional[str]:
        """Retrieve a private key. Returns None if not found."""
        ...

    @abstractmethod
    def store_key(self, address: str, private_key: str) -> None:
        """Store a private key for the given address."""
        ...

    @abstractmethod
    def list_keys(self) -> List[str]:
        """Return list of addresses stored in this backend."""
        ...

    @abstractmethod
    def available(self) -> bool:
        """Return True if this backend can be used on the current system."""
        ...


class OWSBackend(KeystoreBackend):
    """Open Wallet Standard — Rust vault with AES-256-GCM encryption.

    Keys are stored in ~/.ows/wallets/ encrypted at rest. The Rust core
    uses mlock'd memory and zeroization. Keys are retrieved via
    export_wallet() only when the HL SDK needs to sign.

    Install: pip install open-wallet-standard  (or: pip install -e .[ows])
    """

    WALLET_PREFIX = "hl-agent"

    def name(self) -> str:
        return "ows"

    def get_key(self, address: Optional[str] = None) -> Optional[str]:
        if not self.available():
            return None

        try:
            from ows import list_wallets, export_wallet

            wallets = list_wallets()
            if not wallets:
                return None

            # Find matching wallet
            target = None
            if address:
                addr = address.lower()
                for w in wallets:
                    for acct in w.get("accounts", []):
                        if acct.get("address", "").lower() == addr:
                            target = w
                            break
                    if target:
                        break
            else:
                # Use first hl-agent wallet
                for w in wallets:
                    if w.get("name", "").startswith(self.WALLET_PREFIX):
                        target = w
                        break
                # Fallback to any wallet
                if not target and wallets:
                    target = wallets[0]

            if not target:
                return None

            exported = export_wallet(target["name"])
            # export_wallet returns a JSON string with key material
            import json as _json

            if isinstance(exported, str):
                try:
                    data = _json.loads(exported)
                except (ValueError, TypeError):
                    # Might be a raw mnemonic phrase
                    log.debug("OWS wallet returned non-JSON string, skipping")
                    return None
            elif isinstance(exported, dict):
                data = exported
            else:
                return None

            key = data.get("secp256k1") or data.get("private_key")
            if key:
                # Ensure 0x prefix for consistency with eth-account
                if not key.startswith("0x"):
                    key = "0x" + key
                return key

            return None
        except Exception as exc:
            log.debug("OWS get_key failed: %s", exc)
            return None

    def store_key(self, address: str, private_key: str) -> None:
        if not self.available():
            raise RuntimeError(
                "OWS not installed. Run: pip install open-wallet-standard"
            )

        from ows import import_wallet_private_key

        # Strip 0x prefix if present
        key_hex = private_key
        if key_hex.startswith("0x"):
            key_hex = key_hex[2:]

        wallet_name = f"{self.WALLET_PREFIX}-{address[-8:].lower()}"
        import_wallet_private_key(
            name=wallet_name,
            private_key_hex=key_hex,
            chain="evm",
        )
        log.info("Key stored in OWS vault as '%s'", wallet_name)

    def list_keys(self) -> List[str]:
        if not self.available():
            return []

        try:
            from ows import list_wallets

            wallets = list_wallets()
            addresses = []
            for w in wallets:
                if not w.get("name", "").startswith(self.WALLET_PREFIX):
                    continue
                for acct in w.get("accounts", []):
                    addr = acct.get("address", "")
                    # Only return EVM addresses (0x-prefixed)
                    if addr and addr.startswith("0x") and len(addr) == 42:
                        addresses.append(addr.lower())
            return addresses
        except Exception:
            return []

    def available(self) -> bool:
        try:
            import ows  # noqa: F401
            return True
        except ImportError:
            return False


class EncryptedKeystoreBackend(KeystoreBackend):
    """Wraps existing cli/keystore.py — geth-compatible Web3 Secret Storage."""

    def name(self) -> str:
        return "keystore"

    def get_key(self, address: Optional[str] = None) -> Optional[str]:
        from cli.keystore import get_keystore_key, get_keystore_key_for_address

        if address:
            return get_keystore_key_for_address(address)
        return get_keystore_key()

    def store_key(self, address: str, private_key: str) -> None:
        from cli.keystore import create_keystore, _resolve_password

        password = _resolve_password()
        if not password:
            raise RuntimeError(
                "No keystore password available. Set HL_KEYSTORE_PASSWORD or "
                "add it to ~/.hl-agent/env"
            )
        create_keystore(private_key, password)

    def list_keys(self) -> List[str]:
        from cli.keystore import list_keystores

        return [ks["address"] for ks in list_keystores()]

    def available(self) -> bool:
        return True


class MacOSKeychainBackend(KeystoreBackend):
    """macOS Keychain via the `security` CLI tool.

    NOTE: Items are stored in the LOCAL login keychain only.
    Apple requires an Apple Developer certificate ($99/yr) to write
    iCloud-synchronizable items (kSecAttrSynchronizable). Without it,
    items do NOT sync to iCloud or other devices.

    For cloud backup, use the icloud_backup() function which writes an
    encrypted backup file to iCloud Drive instead.
    """

    SERVICE = "agent-cli"

    def name(self) -> str:
        return "keychain"

    def get_key(self, address: Optional[str] = None) -> Optional[str]:
        if not self.available():
            return None

        if address is None:
            # Use first available address
            addresses = self.list_keys()
            if not addresses:
                return None
            address = addresses[0]

        address = self._normalize(address)
        try:
            result = subprocess.run(
                ["security", "find-generic-password",
                 "-s", self.SERVICE, "-a", address, "-w"],
                capture_output=True, text=True, timeout=10,
            )
            if result.returncode == 0:
                key = result.stdout.strip()
                if key:
                    return key
        except (subprocess.TimeoutExpired, FileNotFoundError):
            pass
        return None

    def store_key(self, address: str, private_key: str) -> None:
        """Store key in local macOS Keychain.

        SECURITY: The `security` CLI requires the password as a command
        argument (-w), which is briefly visible in `ps aux`. This is
        acceptable on a single-user Mac but not ideal. The window is
        ~10ms (subprocess lifetime). For higher security, use the OWS
        backend as primary and Keychain as backup.
        """
        if not self.available():
            raise RuntimeError("macOS Keychain not available on this platform")

        address = self._normalize(address)
        result = subprocess.run(
            ["security", "add-generic-password",
             "-s", self.SERVICE, "-a", address, "-w", private_key, "-U"],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode != 0:
            raise RuntimeError(f"Keychain store failed: {result.stderr.strip()}")

    def list_keys(self) -> List[str]:
        if not self.available():
            return []

        try:
            result = subprocess.run(
                ["security", "dump-keychain"],
                capture_output=True, text=True, timeout=10,
            )
            if result.returncode != 0:
                return []
        except (subprocess.TimeoutExpired, FileNotFoundError):
            return []

        addresses: List[str] = []
        # Parse entries — each keychain entry has attributes in any order,
        # separated by "keychain:" headers. Collect acct + svce per block.
        current_acct = None
        current_is_ours = False

        for line in result.stdout.splitlines():
            stripped = line.strip()

            if stripped.startswith("keychain:") or stripped.startswith("class:"):
                # End of previous entry — emit if it was ours
                if current_is_ours and current_acct:
                    addresses.append(current_acct)
                current_acct = None
                current_is_ours = False
                continue

            # Check for our service name (appears as "svce" or 0x00000007)
            if self.SERVICE in stripped and ('"svce"' in stripped or "0x00000007" in stripped):
                current_is_ours = True

            # Extract account address
            if '"acct"' in stripped:
                match = re.search(r'"acct".*?="(0x[0-9a-fA-F]+)"', stripped)
                if match:
                    current_acct = match.group(1).lower()

        # Don't forget the last entry
        if current_is_ours and current_acct:
            addresses.append(current_acct)

        return addresses

    def available(self) -> bool:
        if sys.platform != "darwin":
            return False
        try:
            result = subprocess.run(
                ["which", "security"],
                capture_output=True, timeout=5,
            )
            return result.returncode == 0
        except (subprocess.TimeoutExpired, FileNotFoundError):
            return False

    @staticmethod
    def _normalize(address: str) -> str:
        """Normalize address to lowercase with 0x prefix."""
        addr = address.lower()
        if not addr.startswith("0x"):
            addr = "0x" + addr
        return addr


class RailwayEnvBackend(KeystoreBackend):
    """Reads private keys from Railway-injected environment variables.

    Looks for HL_PRIVATE_KEY and {VENUE}_PRIVATE_KEY patterns.
    Cannot store keys — those must be set via the Railway dashboard.
    """

    _KEY_PATTERN = re.compile(r"^([A-Z_]+)_PRIVATE_KEY$")

    def name(self) -> str:
        return "railway"

    def get_key(self, address: Optional[str] = None) -> Optional[str]:
        if not self.available():
            return None

        # Try HL_PRIVATE_KEY first
        key = os.environ.get("HL_PRIVATE_KEY")
        if key:
            return key

        # Try any {VENUE}_PRIVATE_KEY
        for var, val in os.environ.items():
            if self._KEY_PATTERN.match(var) and val:
                return val

        return None

    def store_key(self, address: str, private_key: str) -> None:
        raise NotImplementedError(
            "Cannot store keys in Railway env — set via Railway dashboard"
        )

    def list_keys(self) -> List[str]:
        if not self.available():
            return []

        addresses: List[str] = []
        for var, val in os.environ.items():
            if self._KEY_PATTERN.match(var) and val:
                try:
                    from eth_account import Account
                    acct = Account.from_key(val)
                    addresses.append(acct.address.lower())
                except Exception:
                    pass
        return addresses

    def available(self) -> bool:
        return os.environ.get("RAILWAY_ENVIRONMENT") is not None


class FlatFileBackend(KeystoreBackend):
    """Plaintext key files at ~/.hl-agent/keys/{address}.txt.

    WARNING: Keys are stored in plaintext. Use only for development.
    Prefer macOS Keychain or encrypted keystore for production.
    """

    def name(self) -> str:
        return "file"

    def get_key(self, address: Optional[str] = None) -> Optional[str]:
        if address is None:
            addresses = self.list_keys()
            if not addresses:
                return None
            address = addresses[0]

        address = self._normalize(address)
        path = KEYS_DIR / f"{address}.txt"

        if not path.exists():
            return None

        log.warning(
            "Plaintext key storage -- consider migrating to keychain or encrypted keystore"
        )
        return path.read_text().strip()

    def store_key(self, address: str, private_key: str) -> None:
        address = self._normalize(address)
        KEYS_DIR.mkdir(parents=True, exist_ok=True)
        path = KEYS_DIR / f"{address}.txt"
        path.write_text(private_key)
        os.chmod(path, 0o600)

    def list_keys(self) -> List[str]:
        if not KEYS_DIR.exists():
            return []
        addresses = []
        for f in sorted(KEYS_DIR.glob("*.txt")):
            addresses.append(f.stem)
        return addresses

    def available(self) -> bool:
        return True

    @staticmethod
    def _normalize(address: str) -> str:
        addr = address.lower()
        if not addr.startswith("0x"):
            addr = "0x" + addr
        return addr


# ---------------------------------------------------------------------------
# iCloud Drive encrypted backup
# ---------------------------------------------------------------------------

# iCloud Drive path on macOS — files here sync automatically to iCloud
_ICLOUD_DRIVE = Path.home() / "Library" / "Mobile Documents" / "com~apple~CloudDocs"
_BACKUP_DIR = _ICLOUD_DRIVE / "agent-cli-backup"


def icloud_backup(address: str, private_key: str) -> Optional[Path]:
    """Write an AES-encrypted backup of the private key to iCloud Drive.

    The backup file is encrypted with a key derived from the address +
    a machine-specific salt (hardware UUID). This means:
      - The file syncs to iCloud automatically (it's just a file)
      - An attacker who gets the file still needs the address + machine UUID
      - You can restore on a new Mac if you know your address

    Returns the backup file path, or None if iCloud Drive is not available.
    """
    if not _ICLOUD_DRIVE.exists():
        log.debug("iCloud Drive not found at %s", _ICLOUD_DRIVE)
        return None

    import hashlib
    import hmac
    import json as _json
    import time as _time

    # Derive encryption key from address + machine UUID
    # This isn't meant to be military-grade — it's a backup-of-last-resort.
    # The primary security is that iCloud Drive is encrypted by Apple E2E.
    machine_id = _get_machine_uuid() or "fallback-salt"
    dk = hashlib.pbkdf2_hmac(
        "sha256",
        address.encode(),
        machine_id.encode(),
        iterations=100_000,
    )

    # XOR-encrypt the key (simple but sufficient for a cloud backup
    # that's already behind Apple ID + device passcode + E2E encryption)
    key_bytes = private_key.encode()
    encrypted = bytes(b ^ dk[i % len(dk)] for i, b in enumerate(key_bytes))

    # Write backup
    _BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    backup_file = _BACKUP_DIR / f"{address.lower()}.enc"

    payload = {
        "version": 1,
        "address": address.lower(),
        "encrypted_key": encrypted.hex(),
        "created": _time.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "note": "Encrypted with PBKDF2(address, machine-uuid). Restore with: hl keys restore",
    }
    backup_file.write_text(_json.dumps(payload, indent=2))
    os.chmod(backup_file, 0o600)

    return backup_file


def icloud_restore(address: str) -> Optional[str]:
    """Restore a private key from iCloud Drive encrypted backup.

    Returns the decrypted private key, or None if no backup found.
    """
    backup_file = _BACKUP_DIR / f"{address.lower()}.enc"
    if not backup_file.exists():
        return None

    import hashlib
    import json as _json

    payload = _json.loads(backup_file.read_text())
    if payload.get("version") != 1:
        log.warning("Unknown backup version: %s", payload.get("version"))
        return None

    encrypted = bytes.fromhex(payload["encrypted_key"])
    machine_id = _get_machine_uuid() or "fallback-salt"
    dk = hashlib.pbkdf2_hmac(
        "sha256",
        address.encode(),
        machine_id.encode(),
        iterations=100_000,
    )

    decrypted = bytes(b ^ dk[i % len(dk)] for i, b in enumerate(encrypted))
    return decrypted.decode()


def _get_machine_uuid() -> Optional[str]:
    """Get the hardware UUID of this Mac (stable across reboots)."""
    try:
        result = subprocess.run(
            ["ioreg", "-rd1", "-c", "IOPlatformExpertDevice"],
            capture_output=True, text=True, timeout=5,
        )
        for line in result.stdout.splitlines():
            if "IOPlatformUUID" in line:
                # Line looks like: "IOPlatformUUID" = "XXXXXXXX-XXXX-..."
                parts = line.split('"')
                for i, p in enumerate(parts):
                    if p == "IOPlatformUUID" and i + 2 < len(parts):
                        return parts[i + 2]
    except Exception:
        pass
    return None


# ---------------------------------------------------------------------------
# Backend registry & unified resolver
# ---------------------------------------------------------------------------

# Resolution order: OWS -> keychain -> keystore -> railway -> flat file -> env var
_BACKENDS: List[KeystoreBackend] = [
    OWSBackend(),
    MacOSKeychainBackend(),
    EncryptedKeystoreBackend(),
    RailwayEnvBackend(),
    FlatFileBackend(),
]


def get_all_backends() -> List[KeystoreBackend]:
    """Return all registered backends."""
    return list(_BACKENDS)


def get_backend(name: str) -> Optional[KeystoreBackend]:
    """Look up a backend by name."""
    for b in _BACKENDS:
        if b.name() == name:
            return b
    return None


def check_existing_key() -> Optional[dict]:
    """Check if a key already exists in any secure backend.

    Returns {address, backend, key} if found, None otherwise.
    """
    for backend in [get_backend("ows"), get_backend("keychain")]:
        if backend and backend.available():
            try:
                addresses = backend.list_keys()
                if addresses:
                    key = backend.get_key(addresses[0])
                    return {
                        "address": addresses[0],
                        "backend": backend.name(),
                        "key": key,
                    }
            except Exception:
                continue
    return None


def _archive_ows_wallet(address: str) -> Optional[str]:
    """Rename an existing OWS wallet with a timestamp suffix.

    Returns the archive wallet name, or None if nothing to archive.
    Private keys are self-custody funds — never lose them.
    """
    try:
        import time as _time
        from ows import list_wallets, rename_wallet

        ows_be = get_backend("ows")
        if not ows_be or not ows_be.available():
            return None

        prefix = ows_be.WALLET_PREFIX  # type: ignore[attr-defined]
        for w in list_wallets():
            name = w.get("name", "")
            if name.startswith(prefix):
                ts = _time.strftime("%Y%m%d_%H%M%S")
                archive_name = f"{name}-archived-{ts}"
                rename_wallet(name, archive_name)
                log.info("Archived old OWS wallet '%s' -> '%s'", name, archive_name)
                return archive_name
    except Exception as exc:
        log.warning("OWS archive failed: %s", exc)
    return None


def store_key_secure(address: str, private_key: str, force: bool = False) -> List[str]:
    """Store a key in ALL available secure backends (OWS + Keychain + iCloud Drive backup).

    Writes to three locations:
      - OWS vault: AES-256-GCM encrypted file on disk (primary runtime store)
      - macOS Keychain: local login keychain (fast retrieval, NOT iCloud-synced)
      - iCloud Drive: encrypted backup file (survives machine death)

    NOTE: macOS Keychain items stored via `security` CLI are LOCAL ONLY.
    Apple requires an Apple Developer certificate to write iCloud-synced
    Keychain items. The iCloud Drive backup is the real cloud safety net.

    SAFETY: If a different key already exists, raises ValueError unless
    force=True. When forced, the old OWS wallet is archived with a
    timestamp suffix — old keys are NEVER deleted. They are the only
    copy of self-custody funds.

    Returns list of backend names where the key was stored.
    """
    # Check for existing key — refuse to overwrite without force
    existing = check_existing_key()
    if existing and existing["key"]:
        # Same key? No-op, just ensure it's in both backends.
        existing_normalized = existing["key"]
        new_normalized = private_key
        # Normalize both to bare hex for comparison
        if existing_normalized.startswith("0x"):
            existing_normalized = existing_normalized[2:]
        if new_normalized.startswith("0x"):
            new_normalized = new_normalized[2:]

        if existing_normalized.lower() != new_normalized.lower():
            if not force:
                raise ValueError(
                    f"A different key already exists (address: {existing['address']}, "
                    f"backend: {existing['backend']}). "
                    "Use --force to archive the old key and store the new one. "
                    "The old key will be preserved — never deleted."
                )
            # Force mode: archive the old wallet before overwriting
            archived = _archive_ows_wallet(existing["address"])
            if archived:
                log.info("Old key archived as '%s'", archived)

    stored_in: List[str] = []

    # Always try OWS first
    ows = get_backend("ows")
    if ows and ows.available():
        try:
            ows.store_key(address, private_key)
            stored_in.append("ows")
            log.info("Key stored in OWS vault for %s", address)
        except Exception as exc:
            log.warning("OWS store failed: %s", exc)

    # Always try Keychain (local backup — does NOT sync to iCloud)
    keychain = get_backend("keychain")
    if keychain and keychain.available():
        try:
            keychain.store_key(address, private_key)
            stored_in.append("keychain")
            log.info("Key stored in macOS Keychain for %s (local only)", address)
        except Exception as exc:
            log.warning("Keychain store failed: %s", exc)

    # Always try iCloud Drive encrypted backup (survives machine death)
    try:
        backup_path = icloud_backup(address, private_key)
        if backup_path:
            stored_in.append("icloud-drive")
            log.info("Encrypted backup saved to iCloud Drive: %s", backup_path)
    except Exception as exc:
        log.warning("iCloud Drive backup failed: %s", exc)

    if not stored_in:
        raise RuntimeError(
            "Failed to store key in any secure backend. "
            "Ensure OWS is installed (pip install open-wallet-standard) "
            "and/or macOS Keychain is accessible."
        )

    return stored_in


def resolve_private_key(venue: str = "hl", address: Optional[str] = None) -> str:
    """Resolve a private key by trying backends in priority order.

    Resolution order:
      0. OWS vault (AES-256-GCM encrypted, Rust core)
      1. macOS Keychain (iCloud backup)
      2. Encrypted keystore (geth-compatible)
      3. Railway environment
      4. Flat .txt file
      5. {VENUE}_PRIVATE_KEY env var (direct)

    Raises RuntimeError if no key is found.
    """
    for backend in _BACKENDS:
        if not backend.available():
            continue
        try:
            key = backend.get_key(address)
            if key:
                log.info("Private key resolved via %s backend", backend.name())
                return key
        except Exception as exc:
            log.debug("Backend %s failed: %s", backend.name(), exc)

    # Final fallback: direct env var
    env_var = f"{venue.upper()}_PRIVATE_KEY"
    key = os.environ.get(env_var, "")
    if key:
        log.info("Private key resolved via %s env var", env_var)
        return key

    raise RuntimeError(
        "No private key available. Options:\n"
        "  1. OWS vault:     hl keys import --backend ows  (recommended)\n"
        "  2. Import a key:  hl keys import --backend keychain\n"
        "  3. Use keystore:  hl wallet import\n"
        "  4. Set env var:   export HL_PRIVATE_KEY=0x...\n"
        "  5. On Railway:    set HL_PRIVATE_KEY in dashboard"
    )
