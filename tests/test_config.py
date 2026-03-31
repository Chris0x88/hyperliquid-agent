"""Tests for cli/config.py — TradingConfig loading and conversion."""
import os
import pytest
import tempfile
from pathlib import Path
from unittest.mock import patch

from typing import Any, Dict, Optional

from cli.config import TradingConfig


@pytest.fixture(autouse=True)
def _isolate_credentials(monkeypatch):
    """Ensure OWS and Keychain don't leak real keys into tests."""
    from common.credentials import OWSBackend, MacOSKeychainBackend
    monkeypatch.setattr(OWSBackend, "available", lambda self: False)
    monkeypatch.setattr(MacOSKeychainBackend, "available", lambda self: False)


class TestDefaults:
    def test_default_values(self):
        cfg = TradingConfig()
        assert cfg.strategy == "avellaneda_mm"
        assert cfg.instrument == "ETH-PERP"
        assert cfg.mainnet is False
        assert cfg.dry_run is False
        assert cfg.max_leverage == 3.0

    def test_default_is_testnet_risk(self):
        cfg = TradingConfig()
        assert cfg._is_default_risk() is True

    def test_custom_risk_not_default(self):
        cfg = TradingConfig(max_position_qty=20.0)
        assert cfg._is_default_risk() is False


class TestFromYaml:
    def test_loads_valid_yaml(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write("strategy: engine_mm\ninstrument: BTC-PERP\ntick_interval: 30.0\n")
            f.flush()
            cfg = TradingConfig.from_yaml(f.name)
        os.unlink(f.name)
        assert cfg.strategy == "engine_mm"
        assert cfg.instrument == "BTC-PERP"
        assert cfg.tick_interval == 30.0

    def test_empty_yaml(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write("")
            f.flush()
            cfg = TradingConfig.from_yaml(f.name)
        os.unlink(f.name)
        assert cfg.strategy == "avellaneda_mm"  # defaults

    def test_unknown_fields_ignored(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write("strategy: simple_mm\nunknown_field: 42\n")
            f.flush()
            cfg = TradingConfig.from_yaml(f.name)
        os.unlink(f.name)
        assert cfg.strategy == "simple_mm"
        assert not hasattr(cfg, "unknown_field")

    def test_missing_file_raises(self):
        with pytest.raises(FileNotFoundError):
            TradingConfig.from_yaml("/nonexistent/config.yaml")


class TestToRiskLimits:
    def test_testnet_defaults(self):
        cfg = TradingConfig()
        limits = cfg.to_risk_limits()
        assert limits.max_leverage == 3.0

    def test_mainnet_defaults_override(self):
        cfg = TradingConfig(mainnet=True)
        limits = cfg.to_risk_limits()
        # Mainnet should have different (stricter) defaults
        assert limits.max_leverage <= 3.0

    def test_custom_risk_preserved(self):
        cfg = TradingConfig(max_position_qty=20.0, max_leverage=5.0)
        limits = cfg.to_risk_limits()
        assert float(limits.max_position_qty) == 20.0
        assert float(limits.max_leverage) == 5.0


class TestGetPrivateKey:
    def test_env_var_fallback(self):
        cfg = TradingConfig()
        with patch("cli.keystore.get_keystore_key", return_value=None):
            with patch.dict(os.environ, {"HL_PRIVATE_KEY": "0xtest"}):
                key = cfg.get_private_key()
        assert key == "0xtest"

    def test_no_key_raises(self):
        cfg = TradingConfig()
        with patch("cli.keystore.get_keystore_key", return_value=None):
            with patch.dict(os.environ, {}, clear=False):
                os.environ.pop("HL_PRIVATE_KEY", None)
                with pytest.raises(RuntimeError, match="No private key"):
                    cfg.get_private_key()

    def test_keystore_takes_priority(self):
        cfg = TradingConfig()
        with patch("cli.keystore.get_keystore_key", return_value="0xfrom_keystore"):
            key = cfg.get_private_key()
        assert key == "0xfrom_keystore"
