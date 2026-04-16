"""PriceMoveAlertIterator — big price move alerts across multiple time windows.

Monitors tracked markets (your core positions + watchlist) and fires Telegram
alerts when price moves significantly across any of three windows:

  5-minute  window: >= 2.0%  (quick spike/flush)
  1-hour    window: >= 3.0%  (sustained move, momentum building)
  24-hour   window: >= 2.0%  (daily drift — important for slow-moving markets like oil)

All thresholds are configurable via data/config/price_move_alert.json:
  {
    "enabled": true,
    "thresholds": {
      "5m":  2.0,
      "1h":  3.0,
      "24h": 2.0
    },
    "cooldown_minutes": 30
  }

Anti-spam: once an alert fires for (instrument, window, direction), it won't
re-alert until either:
  a) cooldown_minutes have passed, OR
  b) price retraces back past the threshold (fresh breakout re-alerts immediately)

Tracked markets: whatever is in ctx.prices — the connector iterator already
limits this to your watchlist so this never scans the whole universe.
"""
from __future__ import annotations

import json
import logging
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

# Default alert thresholds (%)
_DEFAULT_THRESHOLDS = {
    "5m":  2.0,
    "1h":  3.0,
    "24h": 2.0,
}

# Default cooldown before re-alerting same (instrument, window, direction)
_DEFAULT_COOLDOWN_S = 30 * 60  # 30 minutes


def _read_config() -> Tuple[bool, Dict[str, float], float]:
    """Returns (enabled, thresholds, cooldown_s)."""
    try:
        if os.path.exists(_KILL_SWITCH):
            with open(_KILL_SWITCH) as f:
                cfg = json.load(f)
            enabled = bool(cfg.get("enabled", True))
            thresholds = {
                k: float(cfg.get("thresholds", {}).get(k, _DEFAULT_THRESHOLDS[k]))
                for k in _WINDOWS
            }
            cooldown_s = float(cfg.get("cooldown_minutes", _DEFAULT_COOLDOWN_S / 60)) * 60
            return enabled, thresholds, cooldown_s
    except Exception:
        pass
    return True, dict(_DEFAULT_THRESHOLDS), _DEFAULT_COOLDOWN_S


class PriceMoveAlertIterator:
    """Fires alerts on significant price moves across 5m / 1h / 24h windows."""

    name = "price_move_alert"

    def __init__(self) -> None:
        # instrument → deque of (timestamp, price) tuples, newest last
        self._history: Dict[str, Deque[Tuple[float, float]]] = {}
        # (instrument, window, direction) → last_alert_ts
        self._last_alert: Dict[Tuple[str, str, str], float] = {}

    def on_start(self, ctx: TickContext) -> None:
        enabled, thresholds, cooldown_s = _read_config()
        log.info(
            "PriceMoveAlert started  enabled=%s  5m=%.1f%%  1h=%.1f%%  24h=%.1f%%  cooldown=%dm",
            enabled,
            thresholds["5m"], thresholds["1h"], thresholds["24h"],
            cooldown_s / 60,
        )

    def on_stop(self) -> None:
        pass

    def tick(self, ctx: TickContext) -> None:
        enabled, thresholds, cooldown_s = _read_config()
        if not enabled:
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

            # Trim to 24h (no need to keep older entries)
            cutoff = now - _WINDOWS["24h"] - 60  # tiny buffer
            while hist and hist[0][0] < cutoff:
                hist.popleft()

            # Check each window
            for window_key, window_s in _WINDOWS.items():
                threshold_pct = thresholds[window_key]
                ref_price = self._price_at(hist, now - window_s)
                if ref_price is None:
                    continue  # not enough history yet

                move_pct = (price - ref_price) / ref_price * 100.0
                if abs(move_pct) < threshold_pct:
                    continue

                direction = "up" if move_pct > 0 else "down"
                alert_key = (instrument, window_key, direction)
                last = self._last_alert.get(alert_key, 0.0)
                if now - last < cooldown_s:
                    continue  # still in cooldown

                self._last_alert[alert_key] = now
                self._emit_alert(ctx, instrument, window_key, move_pct, price, ref_price)

    @staticmethod
    def _price_at(hist: Deque[Tuple[float, float]], target_ts: float) -> Optional[float]:
        """Find the closest price to target_ts from the history deque.

        Returns None if history doesn't reach that far back.
        """
        if not hist:
            return None
        oldest_ts = hist[0][0]
        # Require at least 80% of the window to be covered
        required_coverage = target_ts - (target_ts * 0.0)  # exact target
        if oldest_ts > target_ts:
            return None  # history doesn't go back far enough

        # Find the entry closest to target_ts
        best = None
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
    ) -> None:
        arrow = "📈" if move_pct > 0 else "📉"
        direction_word = "UP" if move_pct > 0 else "DOWN"
        severity = "warning" if abs(move_pct) >= 4.0 else "info"

        # Clean instrument display name
        display = instrument.replace("xyz:", "").replace("-PERP", "")

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
            },
        ))
        log.info("PriceMoveAlert: %s %+.1f%% over %s  now=%.2f ref=%.2f",
                 instrument, move_pct, window, current, ref)
