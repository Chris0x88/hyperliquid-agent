"""Tests for encrypted keystore — create, load, list, priority."""
import json
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

# Check if eth_account is available
try:
    import eth_account
    HAS_ETH_ACCOUNT = True
except ImportError:
    HAS_ETH_ACCOUNT = False

_root = str(os.path.join(os.path.dirname(__file__), ".."))
if _root not in sys.path:
    sys.path.insert(0, _root)


@pytest.fixture
def tmp_keystore(tmp_path):
    """Redirect keystore dir to temp directory."""
    ks_dir = tmp_path / "keystore"
    ks_dir.mkdir()
    with patch("cli.keystore.KEYSTORE_DIR", ks_dir):
        yield ks_dir


@pytest.fixture(autouse=True)
def _isolate_credentials(monkeypatch):
    """Ensure OWS and Keychain don't leak real keys into tests."""
    from common.credentials import OWSBackend, MacOSKeychainBackend
    monkeypatch.setattr(OWSBackend, "available", lambda self: False)
    monkeypatch.setattr(MacOSKeychainBackend, "available", lambda self: False)


@pytest.mark.skipif(not HAS_ETH_ACCOUNT, reason="eth_account not installed")
class TestKeystoreCreateLoad:
    def test_create_and_load_roundtrip(self, tmp_keystore):
        from cli.keystore import create_keystore, load_keystore

        # Use a real eth_account key
        from eth_account import Account
        account = Account.create()
        key_hex = account.key.hex()
        password = "test-password-123"

        ks_path = create_keystore(key_hex, password)
        assert ks_path.exists()

        # Verify it's valid JSON
        with open(ks_path) as f:
            data = json.load(f)
        assert "address" in data

        # Load it back
        loaded_key = load_keystore(data["address"], password)
        assert loaded_key == "0x" + key_hex.replace("0x", "")

    def test_wrong_password_fails(self, tmp_keystore):
        from cli.keystore import create_keystore, load_keystore
        from eth_account import Account

        account = Account.create()
        create_keystore(account.key.hex(), "correct-password")

        address = account.address.lower().replace("0x", "")
        with pytest.raises(Exception):
            load_keystore(address, "wrong-password")

    def test_missing_keystore_raises(self, tmp_keystore):
        from cli.keystore import load_keystore

        with pytest.raises(FileNotFoundError):
            load_keystore("0xnonexistent", "password")


@pytest.mark.skipif(not HAS_ETH_ACCOUNT, reason="eth_account not installed")
class TestKeystoreList:
    def test_list_empty(self, tmp_keystore):
        from cli.keystore import list_keystores
        assert list_keystores() == []

    def test_list_after_create(self, tmp_keystore):
        from cli.keystore import create_keystore, list_keystores
        from eth_account import Account

        account = Account.create()
        create_keystore(account.key.hex(), "pass")

        keystores = list_keystores()
        assert len(keystores) == 1
        assert keystores[0]["address"].startswith("0x")

    def test_list_multiple(self, tmp_keystore):
        from cli.keystore import create_keystore, list_keystores
        from eth_account import Account

        for _ in range(3):
            account = Account.create()
            create_keystore(account.key.hex(), "pass")

        keystores = list_keystores()
        assert len(keystores) == 3


@pytest.mark.skipif(not HAS_ETH_ACCOUNT, reason="eth_account not installed")
class TestGetKeystoreKey:
    def test_returns_none_when_no_keystores(self, tmp_keystore):
        from cli.keystore import get_keystore_key
        assert get_keystore_key() is None

    def test_returns_none_when_no_password(self, tmp_keystore):
        from cli.keystore import create_keystore, get_keystore_key
        from eth_account import Account

        account = Account.create()
        create_keystore(account.key.hex(), "pass")

        with patch.dict(os.environ, {}, clear=True):
            assert get_keystore_key() is None

    def test_loads_with_env_password(self, tmp_keystore):
        from cli.keystore import create_keystore, get_keystore_key
        from eth_account import Account

        account = Account.create()
        key_hex = account.key.hex()
        create_keystore(key_hex, "env-pass")

        with patch.dict(os.environ, {"HL_KEYSTORE_PASSWORD": "env-pass"}):
            loaded = get_keystore_key()
            assert loaded == "0x" + key_hex.replace("0x", "")


@pytest.mark.skipif(not HAS_ETH_ACCOUNT, reason="eth_account not installed")
class TestConfigPriority:
    def test_keystore_over_env(self, tmp_keystore):
        """Keystore key should take priority over HL_PRIVATE_KEY env var."""
        from cli.keystore import create_keystore
        from cli.config import TradingConfig
        from eth_account import Account

        account = Account.create()
        key_hex = account.key.hex()
        create_keystore(key_hex, "pass")

        with patch.dict(os.environ, {
            "HL_KEYSTORE_PASSWORD": "pass",
            "HL_PRIVATE_KEY": "0xdifferentkey",
        }):
            cfg = TradingConfig()
            loaded = cfg.get_private_key()
            assert loaded == "0x" + key_hex.replace("0x", "")

    def test_falls_back_to_env(self, tmp_keystore):
        """When no keystore available, falls back to HL_PRIVATE_KEY."""
        from cli.config import TradingConfig

        with patch.dict(os.environ, {
            "HL_PRIVATE_KEY": "0xenvkey123",
        }, clear=True):
            cfg = TradingConfig()
            assert cfg.get_private_key() == "0xenvkey123"

    def test_raises_when_nothing_available(self, tmp_keystore):
        from cli.config import TradingConfig

        with patch.dict(os.environ, {}, clear=True):
            cfg = TradingConfig()
            with pytest.raises(RuntimeError, match="No private key"):
                cfg.get_private_key()
