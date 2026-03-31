"""WebSocket event watcher.

Sits alongside the daemon/heartbeat to monitor live market data via WebSocket.
Listens to 1-minute candles and feeds them to the ConsolidationDetector.
"""
from __future__ import annotations

import logging
import threading
import time
from typing import Callable, Dict, Optional, Any

from hyperliquid.info import Info
from hyperliquid.utils import constants

from common.consolidation import Candle, ConsolidationDetector

log = logging.getLogger("event_watcher")


class EventWatcher:
    """Watches market events via HyperLiquid WebSocket.

    Maintains a daemon thread running the WS connection. Used to feed fast
    price updates (like candles) into the ConsolidationDetector.
    """

    def __init__(self, is_mainnet: bool = True):
        self._is_mainnet = is_mainnet
        base_url = constants.MAINNET_API_URL if is_mainnet else constants.TESTNET_API_URL
        # Info(...) auto-starts the websocket manager in the background
        self.info = Info(base_url, skip_ws=False)
        self._active_subscriptions: Dict[str, int] = {}
        self._callback: Optional[Callable[[Candle, str], None]] = None

    def start(self, callback: Callable[[Candle, str], None]) -> None:
        """Start the event watcher with a callback for new candles.

        Args:
            callback: Function called when a new completed candle arrives.
                      Signature: callback(candle, coin_name)
        """
        self._callback = callback

    def subscribe_candles(self, coin: str, interval: str = "1m") -> None:
        """Subscribe to live candles for a coin.

        Supported intervals usually: 1m, 5m, 15m, 1h, 4h, 1d.
        """
        sub = {"type": "candle", "coin": coin, "interval": interval}

        def _on_candle_msg(msg: Any) -> None:
            if not self._callback:
                return
            try:
                # msg usually looks like:
                # {"channel": "candle", "data": {"c": ..., "h": ..., "l": ..., "o": ..., "v": ..., "t": ...}}
                if msg.get("channel") != "candle":
                    return

                data = msg.get("data", {})
                # It sends partial updates too. Let's just feed every update as a 'latest state' candle
                # if possible. For consolidation, we generally want closed candles, but live is fine if requested.
                # Actually, Hyperliquid 'data' contains the candle details
                open_p = float(data.get("o", 0))
                high_p = float(data.get("h", 0))
                low_p = float(data.get("l", 0))
                close_p = float(data.get("c", 0))
                volume = float(data.get("v", 0))
                ts = float(data.get("t", 0))

                c = Candle(
                    open=open_p,
                    high=high_p,
                    low=low_p,
                    close=close_p,
                    volume=volume,
                    timestamp=ts,
                )
                self._callback(c, coin)
            except Exception as e:
                log.warning("Failed to parse candle message %s: %s", msg, e)

        sub_id = self.info.subscribe(sub, _on_candle_msg)
        self._active_subscriptions[coin] = sub_id
        log.info("Subscribed to %s candles for %s (sub_id=%d)", interval, coin, sub_id)

    def unsubscribe_all(self) -> None:
        """Unsubscribe from all active subscriptions."""
        for coin, sub_id in self._active_subscriptions.items():
            try:
                sub = {"type": "candle", "coin": coin, "interval": "1m"}
                self.info.unsubscribe(sub, sub_id)
            except Exception as e:
                log.warning("Failed to unsubscribe %s: %s", coin, e)
        self._active_subscriptions.clear()

    def stop(self) -> None:
        """Stop the websocket connection."""
        self.unsubscribe_all()
        try:
            self.info.disconnect_websocket()
        except RuntimeError:
            pass
