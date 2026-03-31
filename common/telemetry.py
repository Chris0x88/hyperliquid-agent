"""Telemetry — behavioral metrics for agent SRE (Site Reliability Engineering).

Inspired by Google ADK's approach of treating agents as monitorable services.
Tracks per-cycle metrics and writes them to a JSON file that the AI copilot
can read to monitor its own health.

Writes to:  state/telemetry.json  (overwritten each cycle)
"""
from __future__ import annotations

import json
import logging
import os
import time
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

log = logging.getLogger("telemetry")

DEFAULT_STATE_DIR = Path(__file__).resolve().parent.parent / "state"


@dataclass
class ActionMetric:
    """Metrics for a single named action within a cycle."""
    name: str
    elapsed_s: float
    status: str          # "ok", "timeout", "error"
    error: Optional[str] = None
    ts: float = 0.0


@dataclass
class CycleMetrics:
    """Aggregate metrics for one heartbeat or daemon cycle."""
    component: str                           # "heartbeat" or "daemon"
    cycle_start: float = 0.0
    cycle_end: float = 0.0
    cycle_duration_s: float = 0.0
    actions: List[ActionMetric] = field(default_factory=list)

    # Aggregate counts
    total_actions: int = 0
    ok_count: int = 0
    error_count: int = 0
    timeout_count: int = 0

    # API health
    api_calls: int = 0
    api_failures: int = 0

    # Trading actions this cycle
    stops_placed: int = 0
    stops_failed: int = 0
    orders_executed: int = 0

    def finalize(self) -> None:
        """Compute aggregate counts from the actions list."""
        self.total_actions = len(self.actions)
        self.ok_count = sum(1 for a in self.actions if a.status == "ok")
        self.error_count = sum(1 for a in self.actions if a.status == "error")
        self.timeout_count = sum(1 for a in self.actions if a.status == "timeout")
        if self.cycle_end > 0 and self.cycle_start > 0:
            self.cycle_duration_s = round(self.cycle_end - self.cycle_start, 2)


class TelemetryRecorder:
    """Records per-cycle metrics and persists them to a JSON file.

    Usage:
        tel = TelemetryRecorder("heartbeat")
        tel.start_cycle()
        tel.record("check_stops", 0.3, "ok")
        tel.record("place_stop", 1.2, "error", "API timeout")
        tel.increment_api_call(success=True)
        tel.increment_stop(success=False)
        tel.end_cycle()  # writes state/telemetry.json
    """

    def __init__(self, component: str, state_dir: Optional[Path] = None):
        self.component = component
        self.state_dir = Path(state_dir) if state_dir else DEFAULT_STATE_DIR
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.filepath = self.state_dir / "telemetry.json"
        self._current: Optional[CycleMetrics] = None

        # Rolling history for trend detection (last N cycles)
        self._history: List[Dict[str, Any]] = []
        self._max_history = 30

    def start_cycle(self) -> None:
        """Begin a new measurement cycle."""
        self._current = CycleMetrics(
            component=self.component,
            cycle_start=time.time(),
        )

    def record(self, name: str, elapsed_s: float, status: str,
               error: Optional[str] = None) -> None:
        """Record a single action within the current cycle."""
        if not self._current:
            return
        self._current.actions.append(ActionMetric(
            name=name,
            elapsed_s=round(elapsed_s, 3),
            status=status,
            error=error,
            ts=time.time(),
        ))

    def increment_api_call(self, success: bool = True) -> None:
        if not self._current:
            return
        self._current.api_calls += 1
        if not success:
            self._current.api_failures += 1

    def increment_stop(self, success: bool = True) -> None:
        if not self._current:
            return
        if success:
            self._current.stops_placed += 1
        else:
            self._current.stops_failed += 1

    def increment_orders(self, count: int = 1) -> None:
        if not self._current:
            return
        self._current.orders_executed += count

    def end_cycle(self) -> None:
        """Finalize the current cycle and write metrics to disk."""
        if not self._current:
            return

        self._current.cycle_end = time.time()
        self._current.finalize()

        # Add to history
        summary = {
            "component": self._current.component,
            "cycle_duration_s": self._current.cycle_duration_s,
            "total_actions": self._current.total_actions,
            "ok": self._current.ok_count,
            "errors": self._current.error_count,
            "timeouts": self._current.timeout_count,
            "api_calls": self._current.api_calls,
            "api_failures": self._current.api_failures,
            "stops_placed": self._current.stops_placed,
            "stops_failed": self._current.stops_failed,
            "orders": self._current.orders_executed,
            "ts": self._current.cycle_end,
        }
        self._history.append(summary)
        if len(self._history) > self._max_history:
            self._history = self._history[-self._max_history:]

        # Write to file — atomic via tmp + rename
        output = {
            "latest": summary,
            "current_cycle_actions": [asdict(a) for a in self._current.actions],
            "history": self._history,
        }

        tmp_path = self.filepath.with_suffix(".tmp")
        try:
            with open(tmp_path, "w") as f:
                json.dump(output, f, indent=2, default=str)
            os.replace(tmp_path, self.filepath)
            log.debug("Telemetry written: %s (%.1fs cycle, %d actions)",
                      self.filepath, self._current.cycle_duration_s,
                      self._current.total_actions)
        except Exception as e:
            log.warning("Failed to write telemetry: %s", e)

        self._current = None

    @property
    def current_cycle(self) -> Optional[CycleMetrics]:
        return self._current
