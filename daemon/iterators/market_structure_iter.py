"""MarketStructureIterator — computes pre-digested market snapshots each tick.

Runs AFTER connector (needs prices) and BEFORE thesis_engine / execution_engine.
Populates ctx.market_snapshots so downstream consumers get pre-computed
technical analysis without touching raw candles.

Recomputation cadence: every 5 minutes (not every tick — indicators don't
change meaningfully on 60s intervals, and this saves compute).
"""
from __future__ import annotations

import logging
import time
from decimal import Decimal
from typing import Any, Dict, List, Optional

import requests

from daemon.context import TickContext
from common.market_snapshot import MarketSnapshot, build_snapshot_from_candles, render_snapshot
from engines.data.candle_cache import CandleCache

log = logging.getLogger("daemon.market_structure")

# Recompute every 5 minutes — indicators on 1h/4h candles barely move each tick
RECOMPUTE_INTERVAL_S = 300

# Markets that consume 1m candles from the cache (sub-system 4 classifier).
# Kept narrow to limit API load — 1m candles for 10 markets × 5min refresh
# = 120 requests/hour, whereas 2 markets = 24 requests/hour.
_OIL_CLASSIFIER_MARKETS = frozenset({
    "xyz:BRENTOIL",
    "xyz:CL",
})


class MarketStructureIterator:
    """Computes MarketSnapshot for each tracked market and injects into TickContext."""

    name = "market_structure"

    def __init__(
        self,
        candle_cache: Optional[CandleCache] = None,
        intervals: Optional[List[str]] = None,
        recompute_s: int = RECOMPUTE_INTERVAL_S,
    ):
        self._cache = candle_cache
        self._intervals = intervals or ["1h", "4h", "1d"]
        self._recompute_s = recompute_s
        self._last_compute: float = 0.0
        self._snapshots: Dict[str, MarketSnapshot] = {}

    def on_start(self, ctx: TickContext) -> None:
        """Initialize cache if not provided, then compute first snapshots."""
        if self._cache is None:
            try:
                self._cache = CandleCache()
            except Exception as e:
                log.warning("MarketStructure: failed to open candle cache: %s", e)
        self._compute(ctx)

    def on_stop(self) -> None:
        pass

    def tick(self, ctx: TickContext) -> None:
        now = time.monotonic()
        if now - self._last_compute < self._recompute_s:
            # Inject cached snapshots without recomputing
            ctx.market_snapshots.update(self._snapshots)
            return
        self._compute(ctx)

    def _refresh_candles(self, markets: set, lookback_hours: int = 168) -> None:
        """Fetch fresh candles from HL API for all markets and store in cache.

        Mirrors telegram_agent._refresh_candle_cache — fetches 1h, 4h, 1d
        for every market on a 1h staleness threshold, and 1m on a 5-min
        threshold for the oil instruments (sub-system 4 classifier
        consumer). The 1m extension was added 2026-04-09 — prior to
        that, bot_classifier had to direct-fetch from HL per poll
        because the cache never held 1m data.
        """
        if not self._cache:
            return

        now_ms = int(time.time() * 1000)
        # Per-interval staleness + lookback policy
        refresh_policy = [
            # (interval, stale_after_ms, lookback_ms, market_filter)
            ("1h", 3_600_000, lookback_hours * 3_600_000, None),
            ("4h", 3_600_000, lookback_hours * 3_600_000, None),
            ("1d", 3_600_000, lookback_hours * 3_600_000, None),
            # 1m: cache only for the oil classifier's targets, 5-min
            # staleness, 120-minute lookback (lines up with
            # bot_classifier's 60-min lookback window + a safety buffer).
            ("1m", 300_000, 120 * 60_000, _OIL_CLASSIFIER_MARKETS),
        ]

        for coin in markets:
            for interval, stale_after_ms, lookback_ms, market_filter in refresh_policy:
                if market_filter is not None and coin not in market_filter:
                    continue
                try:
                    date_range = self._cache.date_range(coin, interval)
                    if date_range and (now_ms - date_range[1]) < stale_after_ms:
                        continue  # Fresh enough

                    start_ms = date_range[1] if date_range else now_ms - lookback_ms

                    payload = {
                        "type": "candleSnapshot",
                        "req": {"coin": coin, "interval": interval,
                                "startTime": start_ms, "endTime": now_ms},
                    }
                    r = requests.post("https://api.hyperliquid.xyz/info",
                                      json=payload, timeout=10)
                    if r.status_code == 200:
                        candles = r.json()
                        if isinstance(candles, list) and candles:
                            stored = self._cache.store_candles(coin, interval, candles)
                            if stored:
                                log.info("MarketStructure: cached %d %s candles for %s",
                                         stored, interval, coin)
                    time.sleep(0.15)
                except Exception as e:
                    log.debug("MarketStructure: candle refresh failed for %s %s: %s",
                              coin, interval, e)

    def _compute(self, ctx: TickContext) -> None:
        self._last_compute = time.monotonic()
        now_ms = int(time.time() * 1000)
        lookback_ms = 30 * 86_400_000  # 30 days

        # Determine which markets to compute snapshots for
        # Start with watchlist (all tracked markets), then add positions + thesis
        markets = set()
        try:
            from common.watchlist import get_watchlist_coins
            markets.update(get_watchlist_coins())
        except Exception:
            pass
        for pos in ctx.positions:
            if hasattr(pos, "instrument"):
                markets.add(pos.instrument)
            elif hasattr(pos, "coin"):
                markets.add(pos.coin)
        for market in ctx.thesis_states:
            markets.add(market)
        for market in ctx.prices:
            markets.add(market)

        if not markets:
            return

        # Refresh candle cache for all markets (fills gaps for xyz:GOLD, xyz:SILVER, etc.)
        self._refresh_candles(markets)

        # Fetch prices for markets not in ctx.prices (watchlist coins may not be
        # in the Connector's instrument list)
        missing = [m for m in markets if m not in ctx.prices or float(ctx.prices.get(m, 0)) <= 0]
        if missing:
            try:
                import requests
                all_mids = requests.post("https://api.hyperliquid.xyz/info",
                                         json={"type": "allMids"}, timeout=8).json()
                xyz_mids = requests.post("https://api.hyperliquid.xyz/info",
                                         json={"type": "allMids", "dex": "xyz"}, timeout=8).json()
                all_mids.update(xyz_mids)
                for m in missing:
                    if m in all_mids:
                        ctx.prices[m] = Decimal(str(all_mids[m]))
            except Exception as e:
                log.debug("MarketStructure: failed to fetch missing prices: %s", e)

        computed = 0
        for market in markets:
            price = float(ctx.prices.get(market, 0))
            if price <= 0:
                continue

            # Try TickContext candles first (already fetched by connector)
            candle_sets = ctx.candles.get(market, {})

            # Fall back to cache if context doesn't have candles
            if not candle_sets and self._cache:
                candle_sets = {}
                start_ms = now_ms - lookback_ms
                for interval in self._intervals:
                    raw = self._cache.get_candles(market, interval, start_ms, now_ms)
                    if raw:
                        candle_sets[interval] = raw

            if not candle_sets:
                log.debug("MarketStructure: no candle data for %s — skipping", market)
                continue

            try:
                snap = build_snapshot_from_candles(market, candle_sets, price)
                self._snapshots[market] = snap
                computed += 1
                log.debug(
                    "MarketStructure: %s — %s flags=%s",
                    market,
                    snap.timeframes.get("4h", snap.timeframes.get("1h", None)),
                    snap.flags[:3] if snap.flags else "none",
                )
            except Exception as e:
                log.warning("MarketStructure: failed to compute snapshot for %s: %s", market, e)

        ctx.market_snapshots.update(self._snapshots)

        if computed:
            log.info("MarketStructure: computed %d snapshots (%s)", computed, list(self._snapshots.keys()))
