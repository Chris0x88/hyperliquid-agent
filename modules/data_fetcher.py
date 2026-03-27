"""Data fetcher — bridges HL API candle data into the local cache.

Handles chunking (HL API returns max ~500 candles per call),
rate limiting, and gap detection to avoid redundant fetches.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Optional

from modules.candle_cache import CandleCache, INTERVAL_MS

log = logging.getLogger("data_fetcher")

# HL API returns at most ~500 candles per request
_MAX_CANDLES_PER_REQUEST = 500
# Pause between API calls to avoid rate limits
_RATE_LIMIT_SLEEP = 0.3


@dataclass
class DataFetcher:
    """Fetch candles from Hyperliquid API and store in local cache."""

    cache: CandleCache
    proxy: object  # HLProxy or DirectHLProxy — anything with .get_candles()

    def fetch(
        self,
        coin: str,
        interval: str,
        start_ms: int,
        end_ms: int,
        source_label: str = "api",
    ) -> int:
        """Fetch candles from HL API in chunks and store in cache.

        Returns total number of new candles stored.
        """
        # Preserve xyz: prefix for spot tokens (API expects lowercase prefix)
        if ":" in coin:
            prefix, name = coin.split(":", 1)
            coin = f"{prefix.lower()}:{name.upper()}"
        else:
            coin = coin.upper()
        interval_ms = INTERVAL_MS.get(interval)
        if not interval_ms:
            raise ValueError(f"Unknown interval '{interval}'. Use: {list(INTERVAL_MS.keys())}")

        # Calculate chunk size in milliseconds
        chunk_ms = _MAX_CANDLES_PER_REQUEST * interval_ms
        total_stored = 0
        current_start = start_ms

        while current_start < end_ms:
            chunk_end = min(current_start + chunk_ms, end_ms)

            try:
                # HLProxy.get_candles() signature: (coin, interval, lookback_ms)
                # But we need absolute timestamps. The SDK's candles_snapshot
                # takes (coin, interval, start_ms, end_ms). Access it via the
                # proxy's underlying _info object if available, otherwise use
                # the lookback-based API.
                candles = self._fetch_chunk(coin, interval, current_start, chunk_end)

                if candles:
                    stored = self.cache.store_candles(coin, interval, candles, source=source_label)
                    self.cache.log_fetch(coin, interval, current_start, chunk_end, len(candles), source_label)
                    total_stored += stored
                    log.info(
                        "Fetched %d candles for %s %s (%d new)",
                        len(candles), coin, interval, stored,
                    )
                else:
                    log.debug("No candles returned for %s %s chunk %d-%d", coin, interval, current_start, chunk_end)

            except Exception as exc:
                log.warning("Fetch failed for %s %s chunk %d-%d: %s", coin, interval, current_start, chunk_end, exc)

            current_start = chunk_end
            if current_start < end_ms:
                time.sleep(_RATE_LIMIT_SLEEP)

        return total_stored

    def backfill(self, coin: str, interval: str, days: int) -> int:
        """Convenience: fetch last N days of candles."""
        now_ms = int(time.time() * 1000)
        start_ms = now_ms - (days * 86_400_000)
        return self.fetch(coin, interval, start_ms, now_ms)

    def _fetch_chunk(self, coin: str, interval: str, start_ms: int, end_ms: int):
        """Fetch a single chunk of candles from the HL API."""
        # For spot tokens (xyz: prefix), use the proxy's _candles_snapshot if available
        # (SDK doesn't support xyz: coins natively)
        snapshot_fn = getattr(self.proxy, '_candles_snapshot', None)
        if snapshot_fn:
            return snapshot_fn(coin, interval, start_ms, end_ms)

        # Try the SDK's candles_snapshot directly (takes absolute timestamps)
        info = getattr(self.proxy, '_info', None)
        if info is None:
            inner = getattr(self.proxy, '_proxy', None)
            if inner:
                info = getattr(inner, '_info', None)

        if info and hasattr(info, 'candles_snapshot'):
            return info.candles_snapshot(coin, interval, start_ms, end_ms)

        # Fallback: use the lookback-based API
        lookback_ms = end_ms - start_ms
        return self.proxy.get_candles(coin, interval, lookback_ms)
