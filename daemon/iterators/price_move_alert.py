"""PriceMoveAlertIterator — big price move alerts across multiple time windows.

Monitors tracked markets (your core positions + watchlist) and fires Telegram
alerts when price moves significantly across any of three windows:

  5-minute  window: flat-% OR ATR-relative threshold
  1-hour    window: flat-% OR ATR-relative threshold
  24-hour   window: flat-% OR ATR-relative threshold

--- Config schema (data/config/price_move_alert.json) ---

Flat-% mode (legacy, default if atr_multipliers is absent):
  {
    "enabled": true,
    "thresholds": { "5m": 2.0, "1h": 3.0, "24h": 2.0 },
    "cooldown_minutes": 30
  }

ATR-relative mode (preferred — normalises across asset vol regimes):
  {
    "enabled": true,
    "cooldown_minutes": 30,
    "atr_mode": true,
    "atr_multipliers": { "5m": 3.5, "1h": 2.5, "24h": 2.5 },
    "asset_daily_atr_pct": {
      "BTC":      2.9,
      "BRENTOIL": 1.8,
      "GOLD":     0.75,
      "SILVER":   1.4
    },
    "atr_fallback_pct": 2.0
  }

In ATR mode the effective threshold for a given window is:
    threshold_pct = atr_multiplier[window] * (daily_atr_pct * sqrt(window_minutes / 1440))

where daily_atr_pct comes from asset_daily_atr_pct (stripped of xyz: prefix).
If the asset isn't listed, atr_fallback_pct is used as the daily ATR estimate.

Multiplier guidance (at multiplier M, a standard-normal move fires with
probability 2*(1-Phi(M)) per period):
  3.5 → ~0.047%/period  (5m window: ~0.13 alerts/day per asset)
  2.5 → ~1.24%/period   (1h window: ~0.30 alerts/day per asset)
  2.5 → ~4.55%/period   (24h window: ~0.05 alerts/day per asset)
Total ~0.44 alerts/asset/day across all three windows — comfortably under 1/day.

Anti-spam: once an alert fires for (instrument, window, direction) it won't
re-alert until cooldown_minutes have passed.  The cooldown is kept intact —
this change only tightens the per-window thresholds.

Tracked markets: whatever is in ctx.prices — the connector iterator already
limits this to your watchlist so this never scans the whole universe.
"""
from __future__ import annotations

import json
import logging
import math
import os
import time
from collections import deque
from typing import Deque, Dict, Optional, Tuple

from daemon.context import Alert, TickContext

log = logging.getLogger("daemon.price_move_alert")

_KILL_SWITCH = "data/config/price_move_alert.json"

# Window sizes in seconds
_WINDOWS = {
    "5m":  5 * 60,
    "1h":  60 * 60,
    "24h": 24 * 60 * 60,
}

# Default flat-% thresholds (used when atr_mode=false or absent)
_DEFAULT_THRESHOLDS = {
    "5m":  2.0,
    "1h":  3.0,
    "24h": 2.0,
}

# Default ATR multipliers (used when atr_mode=true)
_DEFAULT_ATR_MULTIPLIERS = {
    "5m":  3.5,
    "1h":  2.5,
    "24h": 2.5,
}

# Default per-asset daily ATR % estimates (stripped coin names, no xyz: prefix)
_DEFAULT_ASSET_DAILY_ATR = {
    "BTC":      2.9,
    "BRENTOIL": 1.8,
    "GOLD":     0.75,
    "SILVER":   1.4,
}

_DEFAULT_ATR_FALLBACK_PCT = 2.0   # used for assets not in asset_daily_atr_pct
_DEFAULT_COOLDOWN_S = 30 * 60     # 30 minutes


def _window_atr_pct(daily_atr_pct: float, window_key: str) -> float:
    """Scale daily ATR to the given window using sqrt-of-time rule."""
    window_minutes = _WINDOWS[window_key] / 60
    return daily_atr_pct * math.sqrt(window_minutes / 1440.0)


def _coin_stripped(instrument: str) -> str:
    """Strip xyz: prefix and -PERP suffix for config lookups."""
    return instrument.replace("xyz:", "").replace("-PERP", "")


class _Config:
    """Parsed config object returned by _read_config()."""

    __slots__ = (
        "enabled",
        "atr_mode",
        "thresholds",           # flat-% thresholds (used when atr_mode=False)
        "atr_multipliers",      # ATR multipliers   (used when atr_mode=True)
        "asset_daily_atr",      # {coin: daily_atr_pct}
        "atr_fallback_pct",
        "cooldown_s",
    )

    def __init__(self) -> None:
        self.enabled = True
        self.atr_mode = False
        self.thresholds: Dict[str, float] = dict(_DEFAULT_THRESHOLDS)
        self.atr_multipliers: Dict[str, float] = dict(_DEFAULT_ATR_MULTIPLIERS)
        self.asset_daily_atr: Dict[str, float] = dict(_DEFAULT_ASSET_DAILY_ATR)
        self.atr_fallback_pct: float = _DEFAULT_ATR_FALLBACK_PCT
        self.cooldown_s: float = _DEFAULT_COOLDOWN_S

    def effective_threshold(self, window_key: str, instrument: str) -> float:
        """Return the effective % threshold for (window, instrument).

        In flat mode this is thresholds[window].
        In ATR mode it is atr_multipliers[window] * window_atr_pct(asset_daily_atr).
        """
        if not self.atr_mode:
            return self.thresholds[window_key]

        coin = _coin_stripped(instrument)
        daily_atr = self.asset_daily_atr.get(coin, self.atr_fallback_pct)
        w_atr = _window_atr_pct(daily_atr, window_key)
        return self.atr_multipliers[window_key] * w_atr


def _read_config() -> _Config:
    """Load and parse price_move_alert.json; fall back to safe defaults."""
    cfg_obj = _Config()
    try:
        if os.path.exists(_KILL_SWITCH):
            with open(_KILL_SWITCH) as f:
                raw = json.load(f)

            cfg_obj.enabled = bool(raw.get("enabled", True))
            cfg_obj.cooldown_s = float(raw.get("cooldown_minutes", _DEFAULT_COOLDOWN_S / 60)) * 60
            cfg_obj.atr_mode = bool(raw.get("atr_mode", False))

            # Flat-% thresholds
            flat = raw.get("thresholds", {})
            cfg_obj.thresholds = {
                k: float(flat.get(k, _DEFAULT_THRESHOLDS[k]))
                for k in _WINDOWS
            }

            # ATR multipliers
            mults = raw.get("atr_multipliers", {})
            cfg_obj.atr_multipliers = {
                k: float(mults.get(k, _DEFAULT_ATR_MULTIPLIERS[k]))
                for k in _WINDOWS
            }

            # Per-asset daily ATR
            asset_atr = raw.get("asset_daily_atr_pct", {})
            cfg_obj.asset_daily_atr = {
                k: float(v) for k, v in asset_atr.items()
            } if asset_atr else dict(_DEFAULT_ASSET_DAILY_ATR)

            cfg_obj.atr_fallback_pct = float(raw.get("atr_fallback_pct", _DEFAULT_ATR_FALLBACK_PCT))
    except Exception:
        pass  # return safe defaults
    return cfg_obj


class PriceMoveAlertIterator:
    """Fires alerts on significant price moves across 5m / 1h / 24h windows.

    Supports both flat-% and ATR-relative thresholds; see module docstring.
    """

    name = "price_move_alert"

    def __init__(self) -> None:
        # instrument → deque of (timestamp, price) tuples, newest last
        self._history: Dict[str, Deque[Tuple[float, float]]] = {}
        # (instrument, window, direction) → last_alert_ts
        self._last_alert: Dict[Tuple[str, str, str], float] = {}

    def on_start(self, ctx: TickContext) -> None:
        cfg = _read_config()
        if cfg.atr_mode:
            log.info(
                "PriceMoveAlert started  enabled=%s  mode=ATR  5m=%.1fx  1h=%.1fx  24h=%.1fx  cooldown=%dm",
                cfg.enabled,
                cfg.atr_multipliers["5m"], cfg.atr_multipliers["1h"], cfg.atr_multipliers["24h"],
                cfg.cooldown_s / 60,
            )
        else:
            log.info(
                "PriceMoveAlert started  enabled=%s  mode=flat%%  5m=%.1f%%  1h=%.1f%%  24h=%.1f%%  cooldown=%dm",
                cfg.enabled,
                cfg.thresholds["5m"], cfg.thresholds["1h"], cfg.thresholds["24h"],
                cfg.cooldown_s / 60,
            )

    def on_stop(self) -> None:
        pass

    def tick(self, ctx: TickContext) -> None:
        cfg = _read_config()
        if not cfg.enabled:
            return

        now = time.time()
        prices = ctx.prices or {}

        for instrument, price_dec in prices.items():
            try:
                price = float(price_dec)
                if price <= 0:
                    continue
            except (TypeError, ValueError):
                continue

            # Append to history
            if instrument not in self._history:
                self._history[instrument] = deque()
            hist = self._history[instrument]
            hist.append((now, price))

            # Trim to 24h + buffer
            cutoff = now - _WINDOWS["24h"] - 60
            while hist and hist[0][0] < cutoff:
                hist.popleft()

            # Check each window
            for window_key, window_s in _WINDOWS.items():
                threshold_pct = cfg.effective_threshold(window_key, instrument)
                ref_price = self._price_at(hist, now - window_s)
                if ref_price is None:
                    continue  # not enough history yet

                move_pct = (price - ref_price) / ref_price * 100.0
                if abs(move_pct) < threshold_pct:
                    continue

                direction = "up" if move_pct > 0 else "down"
                alert_key = (instrument, window_key, direction)
                last = self._last_alert.get(alert_key, 0.0)
                if now - last < cfg.cooldown_s:
                    continue  # still in cooldown

                self._last_alert[alert_key] = now
                self._emit_alert(ctx, instrument, window_key, move_pct, price, ref_price, threshold_pct)

    @staticmethod
    def _price_at(hist: Deque[Tuple[float, float]], target_ts: float) -> Optional[float]:
        """Find the closest price to target_ts from the history deque.

        Returns None if history doesn't reach that far back.
        """
        if not hist:
            return None
        if hist[0][0] > target_ts:
            return None  # history doesn't go back far enough

        # Find the entry closest to target_ts
        best: Optional[float] = None
        best_delta = float("inf")
        for ts, price in hist:
            delta = abs(ts - target_ts)
            if delta < best_delta:
                best_delta = delta
                best = price
        return best

    def _emit_alert(
        self,
        ctx: TickContext,
        instrument: str,
        window: str,
        move_pct: float,
        current: float,
        ref: float,
        threshold_pct: float,
    ) -> None:
        arrow = "📈" if move_pct > 0 else "📉"
        direction_word = "UP" if move_pct > 0 else "DOWN"
        severity = "warning" if abs(move_pct) >= threshold_pct * 1.5 else "info"

        # Clean instrument display name
        display = _coin_stripped(instrument)

        msg = (
            f"{arrow} *{display} {direction_word} {abs(move_pct):.1f}%* over {window}\n"
            f"  Now `${current:,.2f}`  was `${ref:,.2f}`"
        )
        ctx.alerts.append(Alert(
            severity=severity,
            source=self.name,
            message=msg,
            data={
                "instrument": instrument,
                "window": window,
                "move_pct": round(move_pct, 2),
                "current_price": current,
                "ref_price": ref,
                "threshold_pct": round(threshold_pct, 4),
            },
        ))
        log.info("PriceMoveAlert: %s %+.1f%% over %s  now=%.2f ref=%.2f  threshold=%.3f%%",
                 instrument, move_pct, window, current, ref, threshold_pct)
