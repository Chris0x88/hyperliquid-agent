"""Memory consolidation iterator — periodic compression of old events.

Runs inside the daemon tick loop. Consolidates old memory events into
bounded summaries so the AI gets accumulated knowledge without unbounded
context growth.

Runs infrequently (once per hour by default) to avoid wasting cycles.
"""
from __future__ import annotations

import logging
import time

log = logging.getLogger("iter.memory_consolidation")

# Run consolidation once per hour (3600 seconds)
_CONSOLIDATION_INTERVAL = 3600


class MemoryConsolidationIterator:
    name = "memory_consolidation"

    def __init__(self):
        self._last_run: float = 0
        self._run_count: int = 0

    def on_start(self, ctx) -> None:
        log.info("Memory consolidation iterator ready (interval: %ds)", _CONSOLIDATION_INTERVAL)

    def tick(self, ctx) -> None:
        now = time.monotonic()
        if now - self._last_run < _CONSOLIDATION_INTERVAL:
            return

        self._last_run = now
        self._run_count += 1

        try:
            from common.memory_consolidator import consolidate

            stats = consolidate()

            if stats.summaries_created > 0:
                log.info(
                    "Consolidation #%d: %d events → %d summaries (%d pruned) in %dms",
                    self._run_count, stats.events_consolidated,
                    stats.summaries_created, stats.summaries_pruned,
                    stats.duration_ms,
                )
            else:
                log.debug("Consolidation #%d: nothing to consolidate (%d events scanned)",
                         self._run_count, stats.events_scanned)

        except Exception as e:
            log.warning("Memory consolidation failed: %s", e)

    def on_stop(self) -> None:
        log.info("Memory consolidation stopped after %d runs", self._run_count)
