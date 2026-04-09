"""Tests for common.markets.MarketRegistry.

Wedge 1 of the Multi-Market Expansion — the registry is pure data + lookup,
so these tests just cover loading, normalisation, and the public API
``get_direction_bias`` / ``is_direction_allowed`` / ``get_max_leverage``.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from common.markets import (
    DEFAULT_CONFIG_PATH,
    MarketRegistry,
    MarketSpec,
    _normalize_symbol,
    get_default_registry,
    reset_default_registry,
)


# ── Helpers ─────────────────────────────────────────────────────────────────

def _write_yaml(path: Path, text: str) -> Path:
    path.write_text(text, encoding="utf-8")
    return path


@pytest.fixture
def shipped_registry() -> MarketRegistry:
    """The real shipped markets.yaml."""
    return MarketRegistry(config_path=DEFAULT_CONFIG_PATH)


@pytest.fixture
def minimal_yaml(tmp_path: Path) -> Path:
    return _write_yaml(
        tmp_path / "markets.yaml",
        """
version: 1
markets:
  BTC:
    direction_bias: neutral
    asset_class: crypto
    max_leverage: 25
  BRENTOIL:
    direction_bias: long_only
    asset_class: commodity
    sub_class: energy
    max_leverage: 10
    exception_subsystems:
      - oil_botpattern
  SHORTONLY:
    direction_bias: short_only
    asset_class: test
    max_leverage: 5
    exception_subsystems:
      - only_long_here
""",
    )


@pytest.fixture(autouse=True)
def _reset_default():
    """Don't let get_default_registry leak between tests."""
    reset_default_registry()
    yield
    reset_default_registry()


# ── _normalize_symbol ──────────────────────────────────────────────────────

class TestNormalizeSymbol:
    def test_bare_symbol_passes_through(self):
        assert _normalize_symbol("BTC") == "BTC"

    def test_xyz_prefix_stripped(self):
        assert _normalize_symbol("xyz:BRENTOIL") == "BRENTOIL"

    def test_xyz_prefix_case_insensitive(self):
        assert _normalize_symbol("XYZ:brentoil") == "BRENTOIL"

    def test_lowercase_upcased(self):
        assert _normalize_symbol("btc") == "BTC"

    def test_whitespace_stripped(self):
        assert _normalize_symbol("  BTC  ") == "BTC"

    def test_empty_returns_empty(self):
        assert _normalize_symbol("") == ""


# ── Shipped registry (the real markets.yaml) ───────────────────────────────

class TestShippedRegistry:
    def test_all_four_markets_present(self, shipped_registry: MarketRegistry):
        symbols = set(shipped_registry.known_symbols())
        assert {"BTC", "BRENTOIL", "GOLD", "SILVER"}.issubset(symbols)

    def test_btc_is_neutral(self, shipped_registry: MarketRegistry):
        assert shipped_registry.get_direction_bias("BTC") == "neutral"

    def test_brentoil_is_long_only(self, shipped_registry: MarketRegistry):
        assert shipped_registry.get_direction_bias("BRENTOIL") == "long_only"

    def test_brentoil_xyz_prefix_resolves(self, shipped_registry: MarketRegistry):
        assert shipped_registry.get_direction_bias("xyz:BRENTOIL") == "long_only"

    def test_gold_is_neutral(self, shipped_registry: MarketRegistry):
        assert shipped_registry.get_direction_bias("GOLD") == "neutral"

    def test_silver_is_neutral(self, shipped_registry: MarketRegistry):
        assert shipped_registry.get_direction_bias("SILVER") == "neutral"

    def test_brentoil_short_blocked_globally(self, shipped_registry: MarketRegistry):
        assert shipped_registry.is_direction_allowed("BRENTOIL", "short") is False

    def test_brentoil_long_allowed_globally(self, shipped_registry: MarketRegistry):
        assert shipped_registry.is_direction_allowed("BRENTOIL", "long") is True

    def test_brentoil_short_allowed_in_oil_botpattern(
        self, shipped_registry: MarketRegistry
    ):
        assert (
            shipped_registry.is_direction_allowed(
                "BRENTOIL", "short", subsystem="oil_botpattern"
            )
            is True
        )

    def test_brentoil_xyz_short_allowed_in_oil_botpattern(
        self, shipped_registry: MarketRegistry
    ):
        assert (
            shipped_registry.is_direction_allowed(
                "xyz:BRENTOIL", "short", subsystem="oil_botpattern"
            )
            is True
        )

    def test_brentoil_short_blocked_in_other_subsystem(
        self, shipped_registry: MarketRegistry
    ):
        assert (
            shipped_registry.is_direction_allowed(
                "BRENTOIL", "short", subsystem="some_other_sub"
            )
            is False
        )

    def test_btc_leverage_cap(self, shipped_registry: MarketRegistry):
        assert shipped_registry.get_max_leverage("BTC") == 25

    def test_brentoil_leverage_cap(self, shipped_registry: MarketRegistry):
        assert shipped_registry.get_max_leverage("BRENTOIL") == 10

    def test_gold_leverage_cap(self, shipped_registry: MarketRegistry):
        assert shipped_registry.get_max_leverage("GOLD") == 10

    def test_silver_leverage_cap(self, shipped_registry: MarketRegistry):
        assert shipped_registry.get_max_leverage("SILVER") == 10

    def test_brentoil_has_roll_calendar(self, shipped_registry: MarketRegistry):
        spec = shipped_registry.get("BRENTOIL")
        assert spec is not None
        assert spec.roll_calendar == "monthly_3rd_to_12th"

    def test_btc_has_no_roll_calendar(self, shipped_registry: MarketRegistry):
        spec = shipped_registry.get("BTC")
        assert spec is not None
        assert spec.roll_calendar is None

    def test_brentoil_exception_subsystems(self, shipped_registry: MarketRegistry):
        spec = shipped_registry.get("BRENTOIL")
        assert spec is not None
        assert "oil_botpattern" in spec.exception_subsystems

    def test_version_parsed(self, shipped_registry: MarketRegistry):
        assert shipped_registry.version >= 1


# ── Direction-allowed rules (synthetic registry) ────────────────────────────

class TestIsDirectionAllowed:
    def test_neutral_market_long_ok(self, minimal_yaml: Path):
        reg = MarketRegistry(config_path=minimal_yaml)
        assert reg.is_direction_allowed("BTC", "long") is True

    def test_neutral_market_short_ok(self, minimal_yaml: Path):
        reg = MarketRegistry(config_path=minimal_yaml)
        assert reg.is_direction_allowed("BTC", "short") is True

    def test_long_only_blocks_short(self, minimal_yaml: Path):
        reg = MarketRegistry(config_path=minimal_yaml)
        assert reg.is_direction_allowed("BRENTOIL", "short") is False

    def test_long_only_allows_long(self, minimal_yaml: Path):
        reg = MarketRegistry(config_path=minimal_yaml)
        assert reg.is_direction_allowed("BRENTOIL", "long") is True

    def test_long_only_short_with_exception_subsystem(self, minimal_yaml: Path):
        reg = MarketRegistry(config_path=minimal_yaml)
        assert (
            reg.is_direction_allowed(
                "BRENTOIL", "short", subsystem="oil_botpattern"
            )
            is True
        )

    def test_long_only_short_with_wrong_subsystem(self, minimal_yaml: Path):
        reg = MarketRegistry(config_path=minimal_yaml)
        assert (
            reg.is_direction_allowed("BRENTOIL", "short", subsystem="news_ingest")
            is False
        )

    def test_short_only_blocks_long(self, minimal_yaml: Path):
        reg = MarketRegistry(config_path=minimal_yaml)
        assert reg.is_direction_allowed("SHORTONLY", "long") is False

    def test_short_only_allows_short(self, minimal_yaml: Path):
        reg = MarketRegistry(config_path=minimal_yaml)
        assert reg.is_direction_allowed("SHORTONLY", "short") is True

    def test_short_only_long_with_exception_subsystem(self, minimal_yaml: Path):
        reg = MarketRegistry(config_path=minimal_yaml)
        assert (
            reg.is_direction_allowed(
                "SHORTONLY", "long", subsystem="only_long_here"
            )
            is True
        )

    def test_direction_flat_always_allowed(self, minimal_yaml: Path):
        reg = MarketRegistry(config_path=minimal_yaml)
        assert reg.is_direction_allowed("BRENTOIL", "flat") is True

    def test_direction_neutral_always_allowed(self, minimal_yaml: Path):
        reg = MarketRegistry(config_path=minimal_yaml)
        assert reg.is_direction_allowed("BRENTOIL", "neutral") is True

    def test_empty_direction_always_allowed(self, minimal_yaml: Path):
        reg = MarketRegistry(config_path=minimal_yaml)
        assert reg.is_direction_allowed("BRENTOIL", "") is True

    def test_direction_case_insensitive(self, minimal_yaml: Path):
        reg = MarketRegistry(config_path=minimal_yaml)
        assert reg.is_direction_allowed("BRENTOIL", "LONG") is True
        assert reg.is_direction_allowed("BRENTOIL", "Short") is False

    def test_unknown_direction_blocked(self, minimal_yaml: Path):
        reg = MarketRegistry(config_path=minimal_yaml)
        assert reg.is_direction_allowed("BTC", "sideways") is False

    def test_unknown_symbol_fails_closed(self, minimal_yaml: Path):
        reg = MarketRegistry(config_path=minimal_yaml)
        assert reg.is_direction_allowed("HYPE", "long") is False


# ── get_* helpers ───────────────────────────────────────────────────────────

class TestGetters:
    def test_get_returns_spec(self, minimal_yaml: Path):
        reg = MarketRegistry(config_path=minimal_yaml)
        spec = reg.get("BTC")
        assert isinstance(spec, MarketSpec)
        assert spec.asset_class == "crypto"
        assert spec.max_leverage == 25

    def test_get_unknown_returns_none(self, minimal_yaml: Path):
        reg = MarketRegistry(config_path=minimal_yaml)
        assert reg.get("HYPE") is None

    def test_get_direction_bias_unknown_raises(self, minimal_yaml: Path):
        reg = MarketRegistry(config_path=minimal_yaml)
        with pytest.raises(KeyError):
            reg.get_direction_bias("HYPE")

    def test_get_max_leverage_unknown_raises(self, minimal_yaml: Path):
        reg = MarketRegistry(config_path=minimal_yaml)
        with pytest.raises(KeyError):
            reg.get_max_leverage("HYPE")

    def test_is_known(self, minimal_yaml: Path):
        reg = MarketRegistry(config_path=minimal_yaml)
        assert reg.is_known("BTC") is True
        assert reg.is_known("xyz:BRENTOIL") is True
        assert reg.is_known("HYPE") is False


# ── Loader error handling ──────────────────────────────────────────────────

class TestLoader:
    def test_missing_file_raises(self, tmp_path: Path):
        with pytest.raises(FileNotFoundError):
            MarketRegistry(config_path=tmp_path / "nope.yaml")

    def test_empty_markets_raises(self, tmp_path: Path):
        path = _write_yaml(tmp_path / "empty.yaml", "version: 1\nmarkets: {}\n")
        with pytest.raises(ValueError, match="no 'markets' section"):
            MarketRegistry(config_path=path)

    def test_invalid_direction_bias_raises(self, tmp_path: Path):
        path = _write_yaml(
            tmp_path / "bad.yaml",
            """
version: 1
markets:
  BTC:
    direction_bias: sideways
    asset_class: crypto
    max_leverage: 10
""",
        )
        with pytest.raises(ValueError, match="direction_bias"):
            MarketRegistry(config_path=path)

    def test_missing_asset_class_raises(self, tmp_path: Path):
        path = _write_yaml(
            tmp_path / "bad.yaml",
            """
version: 1
markets:
  BTC:
    direction_bias: neutral
    max_leverage: 10
""",
        )
        with pytest.raises(ValueError, match="asset_class"):
            MarketRegistry(config_path=path)

    def test_missing_leverage_raises(self, tmp_path: Path):
        path = _write_yaml(
            tmp_path / "bad.yaml",
            """
version: 1
markets:
  BTC:
    direction_bias: neutral
    asset_class: crypto
""",
        )
        with pytest.raises(ValueError, match="max_leverage"):
            MarketRegistry(config_path=path)

    def test_negative_leverage_raises(self, tmp_path: Path):
        path = _write_yaml(
            tmp_path / "bad.yaml",
            """
version: 1
markets:
  BTC:
    direction_bias: neutral
    asset_class: crypto
    max_leverage: 0
""",
        )
        with pytest.raises(ValueError, match="max_leverage"):
            MarketRegistry(config_path=path)

    def test_yaml_keys_are_normalised(self, tmp_path: Path):
        # Keys in YAML given as xyz:BRENTOIL should still be reachable via BRENTOIL
        path = _write_yaml(
            tmp_path / "prefix.yaml",
            """
version: 1
markets:
  "xyz:BRENTOIL":
    direction_bias: long_only
    asset_class: commodity
    max_leverage: 10
""",
        )
        reg = MarketRegistry(config_path=path)
        assert reg.is_known("BRENTOIL")
        assert reg.get_direction_bias("xyz:BRENTOIL") == "long_only"


# ── Default registry singleton ─────────────────────────────────────────────

class TestDefaultRegistry:
    def test_default_registry_loads_shipped_config(self):
        reg = get_default_registry()
        assert reg.is_known("BRENTOIL")
        assert reg.get_direction_bias("BRENTOIL") == "long_only"

    def test_default_registry_is_cached(self):
        reg1 = get_default_registry()
        reg2 = get_default_registry()
        assert reg1 is reg2

    def test_reset_default_registry(self):
        reg1 = get_default_registry()
        reset_default_registry()
        reg2 = get_default_registry()
        assert reg1 is not reg2
