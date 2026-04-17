"""Tests for PriceMoveAlertIterator — ATR-relative threshold tuning.

Two test classes:

  TestAtrThreshold  — unit tests for _Config.effective_threshold() in ATR mode.
    Verifies that the computed % threshold is proportional to the asset's daily
    ATR and the window's sqrt-of-time scaling, and that the fallback fires for
    unlisted assets.

  TestAlertFiring   — integration tests that drive tick() directly with synthetic
    price history and assert which alerts are (or are not) emitted.
    Key scenarios:
      a) Move exactly at threshold fires an alert.
      b) Move below threshold is silent.
      c) Cooldown suppresses duplicate alerts.
      d) Low-vol asset (GOLD) requires a smaller absolute % move to fire.
      e) High-vol asset (BTC) requires a larger absolute % move to fire.
"""
from __future__ import annotations

import math
import time
from collections import deque
from decimal import Decimal
from typing import Dict
from unittest.mock import patch

import pytest

from daemon.context import TickContext
from daemon.iterators.price_move_alert import (
    PriceMoveAlertIterator,
    _Config,
    _coin_stripped,
    _window_atr_pct,
    _read_config,
)


# ── helpers ──────────────────────────────────────────────────────────────────


def _make_ctx(prices: Dict[str, float]) -> TickContext:
    ctx = TickContext()
    ctx.prices = {k: Decimal(str(v)) for k, v in prices.items()}
    return ctx


def _atr_config(
    asset_daily_atr: Dict[str, float] | None = None,
    multipliers: Dict[str, float] | None = None,
    fallback: float = 2.0,
    cooldown_minutes: float = 30.0,
) -> _Config:
    cfg = _Config()
    cfg.atr_mode = True
    cfg.cooldown_s = cooldown_minutes * 60
    if asset_daily_atr is not None:
        cfg.asset_daily_atr = asset_daily_atr
    if multipliers is not None:
        cfg.atr_multipliers = multipliers
    cfg.atr_fallback_pct = fallback
    return cfg


# ── _Config.effective_threshold ───────────────────────────────────────────────


class TestAtrThreshold:
    """_Config.effective_threshold() returns multiplier * window_atr_pct(asset)."""

    def test_btc_24h_threshold(self):
        """BTC daily ATR 2.9% at 24h window with mult 2.5 → 2.9*2.5=7.25%."""
        cfg = _atr_config({"BTC": 2.9}, {"5m": 3.5, "1h": 2.5, "24h": 2.5})
        expected = 2.5 * _window_atr_pct(2.9, "24h")
        assert math.isclose(cfg.effective_threshold("24h", "BTC"), expected, rel_tol=1e-9)

    def test_btc_1h_threshold(self):
        """BTC daily ATR 2.9% at 1h window with mult 2.5 → mult * sqrt(60/1440) * 2.9."""
        cfg = _atr_config({"BTC": 2.9}, {"5m": 3.5, "1h": 2.5, "24h": 2.5})
        expected = 2.5 * _window_atr_pct(2.9, "1h")
        assert math.isclose(cfg.effective_threshold("1h", "BTC"), expected, rel_tol=1e-9)

    def test_gold_has_lower_threshold_than_btc(self):
        """GOLD (0.75% ATR) fires at a lower absolute % than BTC (2.9% ATR)."""
        cfg = _atr_config({"BTC": 2.9, "GOLD": 0.75}, {"5m": 3.5, "1h": 2.5, "24h": 2.5})
        assert cfg.effective_threshold("1h", "GOLD") < cfg.effective_threshold("1h", "BTC")

    def test_xyz_prefix_stripped(self):
        """xyz:BRENTOIL resolves the same as BRENTOIL in asset_daily_atr."""
        cfg = _atr_config({"BRENTOIL": 1.8}, {"5m": 3.5, "1h": 2.5, "24h": 2.5})
        t_bare = cfg.effective_threshold("1h", "BRENTOIL")
        t_prefix = cfg.effective_threshold("1h", "xyz:BRENTOIL")
        assert math.isclose(t_bare, t_prefix, rel_tol=1e-9)

    def test_unlisted_asset_uses_fallback(self):
        """An asset not in asset_daily_atr uses atr_fallback_pct."""
        cfg = _atr_config({}, {"5m": 3.5, "1h": 2.5, "24h": 2.5}, fallback=2.0)
        expected = 2.5 * _window_atr_pct(2.0, "24h")
        assert math.isclose(cfg.effective_threshold("24h", "UNKNOWN"), expected, rel_tol=1e-9)

    def test_flat_mode_ignores_atr(self):
        """In flat mode, effective_threshold() returns the flat % regardless of asset."""
        cfg = _Config()
        cfg.atr_mode = False
        cfg.thresholds = {"5m": 2.0, "1h": 3.0, "24h": 2.0}
        assert cfg.effective_threshold("1h", "BTC") == 3.0
        assert cfg.effective_threshold("1h", "GOLD") == 3.0


# ── Alert firing integration tests ───────────────────────────────────────────


class TestAlertFiring:
    """Drive PriceMoveAlertIterator.tick() with synthetic history and check alerts."""

    def _build_iterator_with_history(
        self,
        instrument: str,
        ref_price: float,
        current_price: float,
        window_key: str,
        now: float | None = None,
    ) -> tuple[PriceMoveAlertIterator, float]:
        """Return (iterator, now) with a single instrument's history pre-loaded.

        The deque contains two entries:
          - (now - window_s - 1, ref_price) — just before the window start
          - (now - window_s + 1, ref_price) — just inside the window (ref point)
        The current price is injected via ctx.prices on the next tick.
        """
        it = PriceMoveAlertIterator()
        if now is None:
            now = time.time()
        window_s = {"5m": 300, "1h": 3600, "24h": 86400}[window_key]

        # Seed history so _price_at() can find ref_price at (now - window_s)
        it._history[instrument] = deque([
            (now - window_s - 1, ref_price),  # older than window — acts as anchor
            (now - window_s + 1, ref_price),  # inside window — closest to target
        ])
        return it, now

    def _tick_once(
        self,
        it: PriceMoveAlertIterator,
        instrument: str,
        current_price: float,
        now: float,
        cfg: _Config,
    ) -> TickContext:
        ctx = _make_ctx({instrument: current_price})
        with patch("daemon.iterators.price_move_alert._read_config", return_value=cfg), \
             patch("daemon.iterators.price_move_alert.time.time", return_value=now):
            it.tick(ctx)
        return ctx

    # -- test: move at threshold fires --

    def test_move_at_threshold_fires_alert(self):
        """A move exactly equal to the threshold (plus epsilon) fires one alert."""
        instrument = "BTC"
        ref = 80_000.0
        cfg = _atr_config({"BTC": 2.9}, {"5m": 3.5, "1h": 2.5, "24h": 2.5})
        thresh = cfg.effective_threshold("1h", instrument)
        current = ref * (1 + (thresh + 0.001) / 100.0)  # just over threshold

        it, now = self._build_iterator_with_history(instrument, ref, current, "1h")
        ctx = self._tick_once(it, instrument, current, now, cfg)

        assert len(ctx.alerts) == 1
        assert ctx.alerts[0].data["window"] == "1h"
        assert ctx.alerts[0].data["instrument"] == instrument

    # -- test: move below threshold is silent --

    def test_move_below_threshold_is_silent(self):
        """A move strictly below the ATR threshold produces no alert."""
        instrument = "BTC"
        ref = 80_000.0
        cfg = _atr_config({"BTC": 2.9}, {"5m": 3.5, "1h": 2.5, "24h": 2.5})
        thresh = cfg.effective_threshold("1h", instrument)
        current = ref * (1 + (thresh - 0.001) / 100.0)  # just below threshold

        it, now = self._build_iterator_with_history(instrument, ref, current, "1h")
        ctx = self._tick_once(it, instrument, current, now, cfg)

        assert ctx.alerts == []

    # -- test: cooldown suppresses second alert --

    def test_cooldown_suppresses_repeat_alert(self):
        """After the first alert, a second tick within cooldown window is silent."""
        instrument = "BTC"
        ref = 80_000.0
        cfg = _atr_config({"BTC": 2.9}, {"5m": 3.5, "1h": 2.5, "24h": 2.5})
        cfg.cooldown_s = 1800  # 30 min
        thresh = cfg.effective_threshold("1h", instrument)
        current = ref * (1 + (thresh + 0.1) / 100.0)

        it, now = self._build_iterator_with_history(instrument, ref, current, "1h")

        # First tick — should fire
        ctx1 = self._tick_once(it, instrument, current, now, cfg)
        assert len(ctx1.alerts) == 1

        # Second tick — same direction, within cooldown (now + 60s)
        it._history[instrument].append((now + 60, current))  # add a new price point
        ctx2 = _make_ctx({instrument: current})
        with patch("daemon.iterators.price_move_alert._read_config", return_value=cfg), \
             patch("daemon.iterators.price_move_alert.time.time", return_value=now + 60):
            it.tick(ctx2)

        assert ctx2.alerts == [], "Repeat alert within cooldown should be suppressed"

    # -- test: ATR proportionality between GOLD and BTC --

    def test_gold_fires_at_lower_absolute_pct_than_btc(self):
        """GOLD (low vol) fires at a lower absolute % move than BTC (high vol).

        This proves ATR-normalisation works: a move that is 3-sigma for GOLD
        is smaller in absolute % terms than a 3-sigma move for BTC.
        """
        cfg = _atr_config({"BTC": 2.9, "GOLD": 0.75}, {"5m": 3.5, "1h": 2.5, "24h": 2.5})
        t_btc = cfg.effective_threshold("24h", "BTC")
        t_gold = cfg.effective_threshold("24h", "GOLD")

        assert t_gold < t_btc, (
            f"GOLD threshold {t_gold:.3f}% should be < BTC threshold {t_btc:.3f}%"
        )
        # Specifically: GOLD 24h ATR ~0.75%, mult 2.5 → ~1.875%
        # BTC   24h ATR ~2.90%, mult 2.5 → ~7.25%
        assert t_gold < 3.0
        assert t_btc > 5.0

    # -- test: disabled iterator does nothing --

    def test_disabled_iterator_produces_no_alerts(self):
        """When enabled=False, no alerts are emitted even on large moves."""
        instrument = "BTC"
        cfg = _atr_config({"BTC": 2.9})
        cfg.enabled = False
        ref = 80_000.0
        current = ref * 1.10  # 10% move — would fire in any threshold regime

        it, now = self._build_iterator_with_history(instrument, ref, current, "1h")
        ctx = _make_ctx({instrument: current})
        with patch("daemon.iterators.price_move_alert._read_config", return_value=cfg), \
             patch("daemon.iterators.price_move_alert.time.time", return_value=now):
            it.tick(ctx)

        assert ctx.alerts == []
