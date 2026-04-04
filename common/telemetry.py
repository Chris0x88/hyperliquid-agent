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
        self._health_window_data: Optional[Dict[str, Any]] = None

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

    def set_health_window(self, data: Dict[str, Any]) -> None:
        """Store health window snapshot to be included in the next end_cycle() write."""
        self._health_window_data = data

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
        output: Dict[str, Any] = {
            "latest": summary,
            "current_cycle_actions": [asdict(a) for a in self._current.actions],
            "history": self._history,
        }
        if self._health_window_data is not None:
            output["health_window"] = self._health_window_data
            self._health_window_data = None

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


# ═══════════════════════════════════════════════════════════════════════
# Health Metrics Window (Passivbot-inspired error budget)
# ═══════════════════════════════════════════════════════════════════════

class HealthWindow:
    """Sliding window health metrics with error budget.

    Passivbot pattern: track events in a rolling window. If errors exceed
    the budget, the system should auto-downgrade (caller's responsibility).

    Usage:
        hw = HealthWindow(window_s=900, error_budget=10)
        hw.record("order_placed")
        hw.record("error")
        if hw.budget_exhausted():
            # auto-downgrade tier
    """

    def __init__(self, window_s: int = 900, error_budget: int = 10):
        from collections import deque
        self._events: deque = deque()
        self._window_s = window_s
        self._error_budget = error_budget

    def record(self, event_type: str) -> None:
        """Record an event. Types: order_placed, order_cancelled, fill, error, timeout."""
        self._events.append((time.time(), event_type))
        self._prune()

    def _prune(self) -> None:
        """Remove events outside the window."""
        cutoff = time.time() - self._window_s
        while self._events and self._events[0][0] < cutoff:
            self._events.popleft()

    def counts(self) -> Dict[str, int]:
        """Return event counts in the current window."""
        self._prune()
        result: Dict[str, int] = {}
        for _, event_type in self._events:
            result[event_type] = result.get(event_type, 0) + 1
        return result

    def error_count(self) -> int:
        """Number of errors in the current window."""
        return self.counts().get("error", 0)

    def budget_exhausted(self) -> bool:
        """True if errors in window >= error_budget."""
        return self.error_count() >= self._error_budget

    def budget_summary(self) -> str:
        """Human-readable summary: '3/10 errors (15min window)'."""
        return f"{self.error_count()}/{self._error_budget} errors ({self._window_s // 60}min window)"

    def to_dict(self) -> dict:
        """For /health command and telemetry file."""
        c = self.counts()
        import resource
        try:
            rss_mb = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / (1024 * 1024)
        except Exception:
            rss_mb = 0
        return {
            "window_s": self._window_s,
            "error_budget": self._error_budget,
            "errors": c.get("error", 0),
            "orders_placed": c.get("order_placed", 0),
            "orders_cancelled": c.get("order_cancelled", 0),
            "fills": c.get("fill", 0),
            "timeouts": c.get("timeout", 0),
            "budget_exhausted": self.budget_exhausted(),
            "rss_mb": round(rss_mb, 1),
        }
