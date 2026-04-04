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
from typing import Any, Dict, List, Optional

from cli.daemon.context import TickContext
from common.market_snapshot import MarketSnapshot, build_snapshot_from_candles, render_snapshot
from modules.candle_cache import CandleCache

log = logging.getLogger("daemon.market_structure")

# Recompute every 5 minutes — indicators on 1h/4h candles barely move each tick
RECOMPUTE_INTERVAL_S = 300


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
        self._intervals = intervals or ["1h", "4h"]
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
