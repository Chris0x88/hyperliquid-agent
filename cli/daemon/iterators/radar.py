"""RadarIterator — wraps modules/radar_engine.py for opportunity scanning."""
from __future__ import annotations

import logging
import time
from typing import Optional

from cli.daemon.context import Alert, TickContext

log = logging.getLogger("daemon.radar")

# Scan every 5 minutes by default
DEFAULT_SCAN_INTERVAL = 300


class RadarIterator:
    name = "radar"

    def __init__(self, scan_interval: int = DEFAULT_SCAN_INTERVAL):
        self._scan_interval = scan_interval
        self._last_scan = 0
        self._engine = None

    def on_start(self, ctx: TickContext) -> None:
        try:
            from modules.radar_engine import OpportunityRadarEngine
            self._engine = OpportunityRadarEngine()
            log.info("RadarIterator started (scan every %ds)", self._scan_interval)
        except Exception as e:
            log.warning("RadarIterator failed to init: %s — will skip", e)

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
            # Radar needs candle data per asset — use what's available
            result = self._engine.scan(
                all_markets=ctx.all_markets,
                asset_candles=ctx.candles,
            )
            self._last_scan = now

            if result and hasattr(result, 'opportunities') and result.opportunities:
                for opp in result.opportunities[:3]:  # top 3
                    ctx.alerts.append(Alert(
                        severity="info",
                        source=self.name,
                        message=f"Radar: {opp.name} score={opp.score:.0f} dir={opp.direction}",
                        data={"opportunity": opp.name, "score": opp.score},
                    ))
                log.info("Radar scan: %d opportunities found", len(result.opportunities))
            else:
                log.debug("Radar scan: no opportunities")

        except Exception as e:
            log.warning("Radar scan failed: %s", e)
