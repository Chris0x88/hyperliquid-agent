"""PulseIterator — wraps modules/pulse_engine.py for momentum detection.

Persists signals to data/research/signals.jsonl for AI agent access and historical review.
"""
from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Optional

from cli.daemon.context import Alert, TickContext

log = logging.getLogger("daemon.pulse")

DEFAULT_SCAN_INTERVAL = 120  # every 2 minutes
SIGNALS_JSONL = "data/research/signals.jsonl"


class PulseIterator:
    name = "pulse"

    def __init__(self, scan_interval: int = DEFAULT_SCAN_INTERVAL):
        self._scan_interval = scan_interval
        self._last_scan = 0
        self._engine = None
        self._scan_history = []

    def on_start(self, ctx: TickContext) -> None:
        Path(SIGNALS_JSONL).parent.mkdir(parents=True, exist_ok=True)
        try:
            from modules.pulse_engine import PulseEngine
            self._engine = PulseEngine()
            log.info("PulseIterator started (scan every %ds)", self._scan_interval)
        except Exception as e:
            log.warning("PulseIterator failed to init: %s — will skip", e)

    def on_stop(self) -> None:
        pass

    def tick(self, ctx: TickContext) -> None:
        if self._engine is None:
            return

        now = int(time.time())
        if self._last_scan > 0 and (now - self._last_scan) < self._scan_interval:
            return

        if not ctx.all_markets:
            return

        try:
            result = self._engine.scan(
                all_markets=ctx.all_markets,
                asset_candles=ctx.candles,
                scan_history=self._scan_history,
            )
            self._last_scan = now

            if result and hasattr(result, 'signals') and result.signals:
                for sig in result.signals[:3]:
                    ctx.alerts.append(Alert(
                        severity="info",
                        source=self.name,
                        message=f"Pulse: {sig.asset} tier={sig.tier} conf={sig.confidence:.0f}%",
                        data={"asset": sig.asset, "tier": sig.tier, "confidence": sig.confidence},
                    ))
                    # Persist to JSONL
                    self._persist_signal(sig, now)

                log.info("Pulse scan: %d signals", len(result.signals))

        except Exception as e:
            log.warning("Pulse scan failed: %s", e)

    def _persist_signal(self, sig, timestamp: int) -> None:
        """Append signal to signals.jsonl for historical tracking."""
        record = {
            "timestamp": timestamp,
            "timestamp_human": time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime(timestamp)),
            "source": "pulse",
            "asset": sig.asset,
            "signal_type": getattr(sig, "signal_type", "unknown"),
            "direction": getattr(sig, "direction", "unknown"),
            "tier": sig.tier,
            "confidence": sig.confidence,
            "oi_delta_pct": getattr(sig, "oi_delta_pct", 0),
            "volume_surge_ratio": getattr(sig, "volume_surge_ratio", 0),
            "funding_shift": getattr(sig, "funding_shift", 0),
        }
        try:
            with open(SIGNALS_JSONL, "a") as f:
                f.write(json.dumps(record) + "\n")
        except Exception as e:
            log.debug("Failed to persist pulse signal: %s", e)
