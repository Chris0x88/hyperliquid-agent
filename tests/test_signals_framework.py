"""Tests for common.signals framework: registry, base, OBV reference impl."""
from __future__ import annotations

import pytest

from common.signals import (
    Candle,
    ChartSpec,
    Signal,
    SignalCard,
    SignalResult,
    all_signals,
    by_category,
    compute,
    get,
    register,
)
from common.signals.registry import _REGISTRY


def _candle(t: int, c: float, v: float = 1000.0) -> Candle:
    # OBV only uses close + volume; others can ignore.
    return {"t": t, "o": c, "h": c, "l": c, "c": c, "v": v}


# ── Registry ──────────────────────────────────────────────────────────────


class TestRegistry:
    def test_obv_auto_registered(self):
        """OBV should be in the registry after importing common.signals."""
        cls = get("obv")
        assert cls is not None
        assert cls.card.name == "On-Balance Volume (OBV)"

    def test_all_signals_returns_classes(self):
        sigs = all_signals()
        assert len(sigs) >= 1
        assert all(issubclass(s, Signal) for s in sigs)

    def test_all_signals_sorted_stable(self):
        """Sort order must be deterministic — UI depends on it."""
        sigs1 = all_signals()
        sigs2 = all_signals()
        assert [s.card.slug for s in sigs1] == [s.card.slug for s in sigs2]

    def test_by_category_groups_correctly(self):
        grouped = by_category()
        assert "volume" in grouped
        assert any(s.card.slug == "obv" for s in grouped["volume"])

    def test_slug_collision_raises(self):
        """Two signals with the same slug must not silently coexist."""
        class Dup(Signal):
            card = SignalCard(
                name="Duplicate", slug="obv", category="volume",
                what="x", basis="x", how_to_read="x", failure_modes="x",
                inputs="x",
            )
            chart_spec = ChartSpec(
                placement="subpane", series_type="line", color="primary",
                axis="raw", series_name="Dup",
            )

            def compute(self, candles, **_):
                return self.new_result()

        with pytest.raises(ValueError, match="slug collision"):
            register(Dup)

    def test_get_returns_none_for_unknown(self):
        assert get("nonexistent_signal_xyz") is None

    def test_compute_raises_keyerror_for_unknown(self):
        with pytest.raises(KeyError, match="Unknown signal slug"):
            compute("nonexistent_signal_xyz", [])


# ── SignalCard / ChartSpec serialization ─────────────────────────────────


class TestSerialization:
    def test_card_to_dict_roundtrip(self):
        card = SignalCard(
            name="T", slug="t", category="volume", what="w", basis="b",
            how_to_read="h", failure_modes="f", inputs="close",
            params={"k": 5},
        )
        d = card.to_dict()
        assert d["slug"] == "t"
        assert d["params"] == {"k": 5}
        # Defensive: mutating the returned dict must not mutate the card.
        d["params"]["k"] = 999
        assert card.params["k"] == 5

    def test_chart_spec_to_dict(self):
        cs = ChartSpec(
            placement="overlay", series_type="line", color="#ff0000",
            axis="price", series_name="Test", priority=3,
        )
        d = cs.to_dict()
        assert d["placement"] == "overlay"
        assert d["priority"] == 3

    def test_result_to_dict_includes_card_and_spec(self):
        result = compute("obv", [_candle(1, 100), _candle(2, 101, 500)])
        d = result.to_dict()
        assert d["slug"] == "obv"
        assert d["card"]["name"] == "On-Balance Volume (OBV)"
        assert d["chart_spec"]["placement"] == "subpane"
        assert isinstance(d["values"], list)


# ── OBV correctness ──────────────────────────────────────────────────────


class TestOBV:
    def test_empty_input(self):
        result = compute("obv", [])
        assert result.values == []
        assert "reason" in result.meta

    def test_single_candle(self):
        result = compute("obv", [_candle(1, 100, 1000)])
        # Single candle → no diff available; meta flags it.
        assert result.values == []
        assert "reason" in result.meta

    def test_two_candles_up(self):
        result = compute("obv", [_candle(1, 100, 1000), _candle(2, 101, 500)])
        # First bar seeds OBV=0; second bar close > prev close adds 500.
        assert result.values == [[1, 0.0], [2, 500.0]]

    def test_two_candles_down(self):
        result = compute("obv", [_candle(1, 100, 1000), _candle(2, 99, 500)])
        assert result.values == [[1, 0.0], [2, -500.0]]

    def test_unchanged_close_preserves_obv(self):
        result = compute("obv", [
            _candle(1, 100, 1000),
            _candle(2, 100, 500),  # unchanged
            _candle(3, 101, 200),  # up
        ])
        assert result.values == [[1, 0.0], [2, 0.0], [3, 200.0]]

    def test_accumulation_sequence(self):
        """Classic accumulation: price flat, volume on up-days dominates."""
        candles = [
            _candle(1, 100, 1000),
            _candle(2, 101, 3000),  # up: +3000
            _candle(3, 100, 1000),  # down: -1000
            _candle(4, 101, 3000),  # up: +3000
            _candle(5, 100, 1000),  # down: -1000
        ]
        result = compute("obv", candles)
        finals = [v for _, v in result.values]
        # Net OBV = 0 + 3000 - 1000 + 3000 - 1000 = 4000 (rising = accumulation)
        assert finals[-1] == 4000.0
        assert result.meta["trend_last_10"] == "rising"

    def test_string_valued_candles(self):
        """Candle cache emits string OHLCV — framework must coerce."""
        candles = [
            {"t": 1, "o": "100", "h": "100", "l": "100", "c": "100", "v": "1000"},
            {"t": 2, "o": "101", "h": "101", "l": "101", "c": "101", "v": "500"},
        ]
        result = compute("obv", candles)
        assert result.values == [[1, 0.0], [2, 500.0]]

    def test_result_includes_card_and_spec(self):
        """Every compute() must stamp the card + chart_spec for the UI."""
        result = compute("obv", [_candle(1, 100), _candle(2, 101)])
        assert result.card is not None
        assert result.card.slug == "obv"
        assert result.chart_spec is not None
        assert result.chart_spec.placement == "subpane"


# ── Card content quality gates ───────────────────────────────────────────


class TestCardQuality:
    """Cards ship to users — enforce minimum documentation quality."""

    @pytest.mark.parametrize("sig_cls", all_signals())
    def test_card_fields_non_empty(self, sig_cls):
        c = sig_cls.card
        assert c.name, f"{c.slug} missing name"
        assert c.slug, f"{sig_cls.__name__} missing slug"
        assert c.what, f"{c.slug} missing 'what' description"
        assert c.basis, f"{c.slug} missing basis/attribution"
        assert c.how_to_read, f"{c.slug} missing how_to_read guide"
        assert c.failure_modes, f"{c.slug} missing failure_modes"
        assert c.inputs, f"{c.slug} missing inputs declaration"

    @pytest.mark.parametrize("sig_cls", all_signals())
    def test_slug_is_snake_case(self, sig_cls):
        slug = sig_cls.card.slug
        assert slug == slug.lower(), f"{slug} must be lowercase"
        assert " " not in slug, f"{slug} must not contain spaces"
        assert "-" not in slug, f"{slug} must use underscores, not dashes"

    @pytest.mark.parametrize("sig_cls", all_signals())
    def test_how_to_read_has_bullets(self, sig_cls):
        """Cards should be bullet-structured, not walls of prose."""
        htr = sig_cls.card.how_to_read
        assert "•" in htr or "\n" in htr, (
            f"{sig_cls.card.slug} how_to_read should use bullets"
        )
