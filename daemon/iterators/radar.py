"""RadarIterator — wraps modules/radar_engine.py for opportunity scanning.

Persists opportunities to data/research/signals.jsonl for AI agent access and historical review.

BUG-FIX 2026-04-17 (deep-dive finding): the iterator relied on
``ctx.candles["BTC"]`` being populated by the connector, but the connector
only fetches candles for instruments in ``ctx.active_strategies`` — empty
in WATCH tier. So every Radar scan in WATCH got ``btc_candles_4h=[]`` and
``asset_candles={}``, causing every deep-dive to silently
``continue`` on ``if not c1h``. Result: zero opportunities ever surfaced
in WATCH despite the iterator running every 5 min. Fix: optionally accept
an adapter and fetch BTC 4h/1h directly when ctx.candles is empty. Cached
across ticks to avoid hammering the API every scan.
"""
from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any, Optional

from daemon.context import Alert, TickContext

log = logging.getLogger("daemon.radar")

# Scan every 5 minutes by default
DEFAULT_SCAN_INTERVAL = 300
SIGNALS_JSONL = "data/research/signals.jsonl"
# How long to trust a cached BTC-context candle batch before refetching.
# 5min suits the radar scan cadence — keeps macro context fresh-enough
# without hammering the HL API every scan.
BTC_CANDLE_CACHE_TTL_S = 300


class RadarIterator:
    name = "radar"

    def __init__(self, scan_interval: int = DEFAULT_SCAN_INTERVAL, adapter: Any = None):
        self._scan_interval = scan_interval
        self._last_scan = 0
        self._engine = None
        # H1: optional adapter for direct BTC candle fetch when ctx.candles
        # is empty (WATCH tier). Iterator works adapter-less too — falls
        # back to "neutral macro" cleanly when BTC candles unavailable.
        self._adapter = adapter
        self._btc_4h_cache: list = []
        self._btc_1h_cache: list = []
        self._btc_cache_ts: float = 0.0

    def on_start(self, ctx: TickContext) -> None:
        Path(SIGNALS_JSONL).parent.mkdir(parents=True, exist_ok=True)
        try:
            from engines.analysis.radar_engine import OpportunityRadarEngine
            self._engine = OpportunityRadarEngine()
            log.info(
                "RadarIterator started (scan every %ds, adapter=%s)",
                self._scan_interval,
                "yes" if self._adapter is not None else "no",
            )
        except Exception as e:
            log.warning("RadarIterator failed to init: %s — will skip", e)

    def _fetch_btc_candles_for_macro(self) -> tuple[list, list]:
        """Pull BTC 4h + 1h candles directly via the adapter when ctx.candles
        is empty. Cached for BTC_CANDLE_CACHE_TTL_S to avoid hammering HL on
        every scan. Returns ``([], [])`` if no adapter or fetch fails — the
        engine handles the degraded case as "neutral macro context" cleanly.
        """
        if self._adapter is None:
            return [], []
        now = time.time()
        if self._btc_4h_cache and (now - self._btc_cache_ts) < BTC_CANDLE_CACHE_TTL_S:
            return self._btc_4h_cache, self._btc_1h_cache
        try:
            # 7 days of 4h ≈ 42 candles; 24h of 1h = 24 — both bounded and cheap
            btc_4h = self._adapter.get_candles("BTC", "4h", lookback_ms=7 * 24 * 3600 * 1000)
            btc_1h = self._adapter.get_candles("BTC", "1h", lookback_ms=24 * 3600 * 1000)
            self._btc_4h_cache = btc_4h or []
            self._btc_1h_cache = btc_1h or []
            self._btc_cache_ts = now
            return self._btc_4h_cache, self._btc_1h_cache
        except Exception as e:
            log.debug("Radar BTC candle fetch failed: %s — using neutral macro", e)
            return [], []

    def on_stop(self) -> None:
        pass

    def tick(self, ctx: TickContext) -> None:
        if self._engine is None:
            return

        now = int(time.time())
        if self._last_scan > 0 and (now - self._last_scan) < self._scan_interval:
            return

        if not ctx.all_markets:
            log.debug("No market data — skipping radar scan")
            return

        try:
            # Radar needs BTC candles for macro context. Prefer ctx.candles
            # when populated (REBALANCE/OPPORTUNISTIC tiers register a BTC
            # strategy slot and connector fetches them). When empty (WATCH),
            # fall back to a direct adapter fetch.
            btc_candles = ctx.candles.get("BTC", ctx.candles.get("BTC-PERP", {}))
            btc_4h = btc_candles.get("4h", [])
            btc_1h = btc_candles.get("1h", [])
            if not btc_4h or not btc_1h:
                btc_4h, btc_1h = self._fetch_btc_candles_for_macro()

            result = self._engine.scan(
                all_markets=ctx.all_markets,
                btc_candles_4h=btc_4h,
                btc_candles_1h=btc_1h,
                asset_candles=ctx.candles,
            )
            self._last_scan = now

            if result and hasattr(result, 'opportunities') and result.opportunities:
                # Populate ctx for downstream consumers (apex_advisor — C3).
                # Serialize to a dict shape ApexEngine.evaluate() expects.
                ctx.radar_opportunities = [
                    {
                        "asset": opp.asset,
                        "direction": opp.direction,
                        "final_score": opp.final_score,
                    }
                    for opp in result.opportunities
                ]

                for opp in result.opportunities[:3]:  # top 3
                    # Note: previous version used opp.name / opp.score which
                    # don't exist on the Opportunity dataclass — that was a
                    # latent bug hidden by the fact that radar has been
                    # producing empty results in current markets. Fixed
                    # inline as part of C3 because the new ctx population
                    # path needs the correct attribute names.
                    ctx.alerts.append(Alert(
                        severity="info",
                        source=self.name,
                        message=f"Radar: {opp.asset} score={opp.final_score:.0f} dir={opp.direction}",
                        data={"asset": opp.asset, "final_score": opp.final_score, "direction": opp.direction},
                    ))
                    # Persist to JSONL
                    self._persist_signal(opp, now)

                log.info("Radar scan: %d opportunities found", len(result.opportunities))
            else:
                # Clear stale opportunities from previous scan
                ctx.radar_opportunities = []
                log.debug("Radar scan: no opportunities")

        except Exception as e:
            log.warning("Radar scan failed: %s", e)

    def _persist_signal(self, opp, timestamp: int) -> None:
        """Append opportunity to signals.jsonl for historical tracking."""
        # Fix: Opportunity dataclass exposes .asset / .final_score, NOT
        # .name / .score. The previous version was a latent crash that
        # never fired because no opportunities were ever produced.
        record = {
            "timestamp": timestamp,
            "timestamp_human": time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime(timestamp)),
            "source": "radar",
            "asset": opp.asset,
            "direction": opp.direction,
            "final_score": opp.final_score,
            "macro_modifier": getattr(opp, "macro_modifier", 0),
        }
        try:
            with open(SIGNALS_JSONL, "a") as f:
                f.write(json.dumps(record) + "\n")
        except Exception as e:
            log.debug("Failed to persist radar signal: %s", e)
