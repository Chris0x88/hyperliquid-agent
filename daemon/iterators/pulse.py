"""PulseIterator — wraps modules/pulse_engine.py for momentum detection.

Persists signals to data/research/signals.jsonl for AI agent access and historical review.

BUG-FIX 2026-04-17 (deep-dive finding): the iterator previously passed
``self._scan_history = []`` to ``engine.scan()`` and **never appended the
result**, so ``len(scan_history) >= cfg.min_scans_for_signal`` was always
False — Pulse silently emitted zero signals forever. There's even a
``PulseHistoryStore`` class in ``engines/analysis/pulse_state.py`` designed
to persist scan history to ``data/pulse/scan-history.json`` (with
``save_scan`` / ``get_history`` / ``from_dict`` round-tripping) — the
iterator just wasn't using it. This rewrite wires the store in:
load-on-start, append-after-scan, and feed the engine the history-of-dicts
shape it expects. Restarts now resume from the last 30 scans on disk.
"""
from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Optional

from daemon.context import Alert, TickContext

log = logging.getLogger("daemon.pulse")

DEFAULT_SCAN_INTERVAL = 120  # every 2 minutes
SIGNALS_JSONL = "data/research/signals.jsonl"


class PulseIterator:
    name = "pulse"

    def __init__(self, scan_interval: int = DEFAULT_SCAN_INTERVAL):
        self._scan_interval = scan_interval
        self._last_scan = 0
        self._engine = None
        self._history_store = None
        self._scan_history: list = []

    def on_start(self, ctx: TickContext) -> None:
        Path(SIGNALS_JSONL).parent.mkdir(parents=True, exist_ok=True)
        try:
            from engines.analysis.pulse_engine import PulseEngine
            from engines.analysis.pulse_state import PulseHistoryStore
            self._engine = PulseEngine()
            self._history_store = PulseHistoryStore()
            # Resume scan history across restarts so the engine doesn't have
            # to re-baseline from zero every time the daemon bounces.
            self._scan_history = self._history_store.get_history()
            log.info(
                "PulseIterator started (scan every %ds, %d scans of history loaded)",
                self._scan_interval, len(self._scan_history),
            )
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

            # BUG-FIX 2026-04-17: persist this scan into history so the next
            # tick's engine call has a baseline. Without this, signals never
            # fire because has_baseline = len(scan_history) >= min_scans_for_signal
            # stays False forever.
            if result is not None:
                try:
                    self._history_store.save_scan(result)
                    # Refresh the in-memory list from the store so it stays
                    # bounded (max_size) and matches what's on disk.
                    self._scan_history = self._history_store.get_history()
                except Exception as persist_err:
                    log.warning("Failed to persist pulse scan history: %s", persist_err)

            if result and hasattr(result, 'signals') and result.signals:
                # Populate ctx for downstream consumers (apex_advisor — C3).
                # Serialize to a dict shape ApexEngine.evaluate() expects.
                ctx.pulse_signals = [
                    {
                        "asset": sig.asset,
                        "signal_type": getattr(sig, "signal_type", "unknown"),
                        "direction": getattr(sig, "direction", "unknown"),
                        "tier": sig.tier,
                        "confidence": sig.confidence,
                    }
                    for sig in result.signals
                ]

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
            else:
                # Clear stale signals from previous scan if this scan found nothing
                ctx.pulse_signals = []

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
