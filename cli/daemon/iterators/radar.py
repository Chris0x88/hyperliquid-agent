"""RadarIterator — wraps modules/radar_engine.py for opportunity scanning.

Persists opportunities to data/research/signals.jsonl for AI agent access and historical review.
"""
from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Optional

from cli.daemon.context import Alert, TickContext

log = logging.getLogger("daemon.radar")

# Scan every 5 minutes by default
DEFAULT_SCAN_INTERVAL = 300
SIGNALS_JSONL = "data/research/signals.jsonl"


class RadarIterator:
    name = "radar"

    def __init__(self, scan_interval: int = DEFAULT_SCAN_INTERVAL):
        self._scan_interval = scan_interval
        self._last_scan = 0
        self._engine = None

    def on_start(self, ctx: TickContext) -> None:
        Path(SIGNALS_JSONL).parent.mkdir(parents=True, exist_ok=True)
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
            # Radar needs BTC candles for macro context
            btc_candles = ctx.candles.get("BTC", ctx.candles.get("BTC-PERP", {}))
            btc_4h = btc_candles.get("4h", [])
            btc_1h = btc_candles.get("1h", [])

            result = self._engine.scan(
                all_markets=ctx.all_markets,
                btc_candles_4h=btc_4h,
                btc_candles_1h=btc_1h,
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
                    # Persist to JSONL
                    self._persist_signal(opp, now)

                log.info("Radar scan: %d opportunities found", len(result.opportunities))
            else:
                log.debug("Radar scan: no opportunities")

        except Exception as e:
            log.warning("Radar scan failed: %s", e)

    def _persist_signal(self, opp, timestamp: int) -> None:
        """Append opportunity to signals.jsonl for historical tracking."""
        record = {
            "timestamp": timestamp,
            "timestamp_human": time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime(timestamp)),
            "source": "radar",
            "asset": opp.name,
            "direction": opp.direction,
            "score": opp.score,
            "btc_macro_modifier": getattr(opp, "btc_macro_modifier", 0),
        }
        try:
            with open(SIGNALS_JSONL, "a") as f:
                f.write(json.dumps(record) + "\n")
        except Exception as e:
            log.debug("Failed to persist radar signal: %s", e)
