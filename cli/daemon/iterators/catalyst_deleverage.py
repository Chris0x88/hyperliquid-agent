"""CatalystDeleverageIterator — reduces position leverage/size ahead of known catalysts.

Architecture:
  - Accepts a list of CatalystEvent dataclasses describing upcoming volatility events
  - On each tick (throttled to 1h), checks current time vs each event_date
  - If within pre_event_hours window and not yet executed:
    - Queues OrderIntent to reduce position by reduce_size_pct (reduce_only, Ioc)
    - Queues Alert for leverage change (cannot call adapter.set_leverage from iterator)
    - Marks catalyst as executed
  - Issues warning alerts at 6h and 1h before event
  - Persists executed state to data/daemon/catalyst_events.json across restarts

Note: Leverage changes require manual confirmation or a separate mechanism.
The iterator can only reduce position size via OrderIntent and alert on leverage targets.
"""
from __future__ import annotations

import json
import logging
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Dict, List, Optional, Set

from cli.daemon.context import Alert, OrderIntent, TickContext

log = logging.getLogger("daemon.catalyst_deleverage")

ZERO = Decimal("0")
HOUR_S = 3600


@dataclass
class CatalystEvent:
    """A known volatility catalyst that triggers pre-emptive deleverage."""
    name: str                                    # "trump_deadline", "contract_roll_bzm6"
    instrument: str                              # "xyz:BRENTOIL"
    event_date: str                              # ISO date: "2026-04-06"
    pre_event_hours: int = 24                    # hours before event to start reducing
    reduce_leverage_to: Optional[float] = None   # target leverage (e.g., 5.0)
    reduce_size_pct: Optional[float] = None      # reduce position by this % (e.g., 0.30 = 30%)
    post_event_hours: int = 12                   # hours after event before restoring
    executed: bool = False

    @property
    def event_dt(self) -> datetime:
        return datetime.fromisoformat(self.event_date).replace(tzinfo=timezone.utc)

    @property
    def event_ts(self) -> float:
        """Event timestamp in seconds."""
        return self.event_dt.timestamp()


class CatalystDeleverageIterator:
    """Automatically reduces position leverage/size ahead of high-volatility catalysts."""
    name = "catalyst_deleverage"

    def __init__(
        self,
        catalysts: Optional[List[CatalystEvent]] = None,
        adapter=None,
        check_interval: int = HOUR_S,
        data_dir: str = "data/daemon",
    ):
        self._catalysts: List[CatalystEvent] = catalysts or []
        self._adapter = adapter
        self._check_interval = check_interval
        self._state_path = Path(data_dir) / "catalyst_events.json"
        self._last_check: int = 0
        self._warned_6h: Set[str] = set()
        self._warned_1h: Set[str] = set()

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def on_start(self, ctx: TickContext) -> None:
        self._state_path.parent.mkdir(parents=True, exist_ok=True)
        self._load_state()
        active = [c for c in self._catalysts if not c.executed]
        log.info(
            "CatalystDeleverageIterator started — %d catalysts (%d pending)",
            len(self._catalysts),
            len(active),
        )
        if active:
            for c in active:
                log.info("  pending: %s on %s @ %s", c.name, c.instrument, c.event_date)

    def on_stop(self) -> None:
        self._save_state()

    # ------------------------------------------------------------------
    # Tick
    # ------------------------------------------------------------------

    def tick(self, ctx: TickContext) -> None:
        now_s = ctx.timestamp // 1000 if ctx.timestamp > 1e12 else ctx.timestamp
        if now_s - self._last_check < self._check_interval:
            return
        self._last_check = now_s

        if not self._catalysts:
            return

        now_dt = datetime.fromtimestamp(now_s, tz=timezone.utc)

        for catalyst in self._catalysts:
            self._process_catalyst(catalyst, now_s, now_dt, ctx)

    # ------------------------------------------------------------------
    # Core logic
    # ------------------------------------------------------------------

    def _process_catalyst(
        self,
        catalyst: CatalystEvent,
        now_s: float,
        now_dt: datetime,
        ctx: TickContext,
    ) -> None:
        event_ts = catalyst.event_ts
        hours_until = (event_ts - now_s) / HOUR_S

        # Already past the post-event window — nothing to do
        if hours_until < -catalyst.post_event_hours:
            return

        # Warning alerts (not gated by executed)
        self._maybe_warn(catalyst, hours_until, ctx)

        # Already executed — skip
        if catalyst.executed:
            return

        # Not yet in the pre-event window
        if hours_until > catalyst.pre_event_hours:
            return

        # --- Within pre-event window: execute deleverage ---
        log.info(
            "Catalyst '%s' triggered — %.1fh until event on %s",
            catalyst.name,
            hours_until,
            catalyst.event_date,
        )

        # Find matching position
        position = None
        for pos in ctx.positions:
            if pos.instrument == catalyst.instrument:
                position = pos
                break

        if position is None:
            log.info("No position in %s — marking catalyst '%s' executed (no-op)",
                     catalyst.instrument, catalyst.name)
            catalyst.executed = True
            self._save_state()
            return

        actions_taken: List[str] = []

        # --- Leverage alert ---
        if catalyst.reduce_leverage_to is not None:
            ctx.alerts.append(Alert(
                severity="warning",
                source=self.name,
                message=(
                    f"CATALYST '{catalyst.name}': Reduce leverage on {catalyst.instrument} "
                    f"to {catalyst.reduce_leverage_to}x before {catalyst.event_date}. "
                    f"Manual confirmation required."
                ),
                data={
                    "catalyst": catalyst.name,
                    "instrument": catalyst.instrument,
                    "target_leverage": catalyst.reduce_leverage_to,
                    "event_date": catalyst.event_date,
                    "action": "reduce_leverage",
                },
            ))
            actions_taken.append(f"leverage alert -> {catalyst.reduce_leverage_to}x")
            log.info("Queued leverage alert for '%s': target %sx",
                     catalyst.name, catalyst.reduce_leverage_to)

        # --- Size reduction ---
        if catalyst.reduce_size_pct is not None and catalyst.reduce_size_pct > 0:
            reduce_qty = abs(position.net_qty) * Decimal(str(catalyst.reduce_size_pct))
            if reduce_qty > ZERO:
                action = "sell" if position.net_qty > ZERO else "buy"
                ctx.order_queue.append(OrderIntent(
                    strategy_name=self.name,
                    instrument=catalyst.instrument,
                    action=action,
                    size=reduce_qty,
                    reduce_only=True,
                    order_type="Ioc",
                    meta={
                        "reason": "catalyst_deleverage",
                        "catalyst": catalyst.name,
                        "reduce_pct": catalyst.reduce_size_pct,
                        "event_date": catalyst.event_date,
                    },
                ))
                actions_taken.append(
                    f"reduce {catalyst.reduce_size_pct*100:.0f}% "
                    f"({float(reduce_qty):.4f} qty)"
                )
                log.info(
                    "Queued size reduction for '%s': %.0f%% of %s (%.4f qty)",
                    catalyst.name,
                    catalyst.reduce_size_pct * 100,
                    catalyst.instrument,
                    float(reduce_qty),
                )

        # --- Summary alert ---
        if actions_taken:
            ctx.alerts.append(Alert(
                severity="warning",
                source=self.name,
                message=(
                    f"CATALYST DELEVERAGE executed for '{catalyst.name}' "
                    f"({catalyst.instrument}, event {catalyst.event_date}): "
                    + "; ".join(actions_taken)
                ),
                data={"catalyst": catalyst.name, "actions": actions_taken},
            ))

        catalyst.executed = True
        self._save_state()

    def _maybe_warn(
        self,
        catalyst: CatalystEvent,
        hours_until: float,
        ctx: TickContext,
    ) -> None:
        """Issue 6h and 1h warning alerts for approaching catalysts."""
        if hours_until <= 0:
            return

        if hours_until <= 6 and catalyst.name not in self._warned_6h:
            ctx.alerts.append(Alert(
                severity="warning",
                source=self.name,
                message=(
                    f"Catalyst '{catalyst.name}' in ~{hours_until:.1f}h "
                    f"({catalyst.instrument}, {catalyst.event_date})"
                    + (f" — executed: positions already reduced" if catalyst.executed else "")
                ),
                data={"catalyst": catalyst.name, "hours_until": round(hours_until, 1)},
            ))
            self._warned_6h.add(catalyst.name)
            log.info("6h warning for catalyst '%s'", catalyst.name)

        if hours_until <= 1 and catalyst.name not in self._warned_1h:
            ctx.alerts.append(Alert(
                severity="critical",
                source=self.name,
                message=(
                    f"Catalyst '{catalyst.name}' IMMINENT — ~{hours_until*60:.0f}min "
                    f"({catalyst.instrument})"
                    + (f" — positions already reduced" if catalyst.executed else " — NOT YET REDUCED")
                ),
                data={"catalyst": catalyst.name, "hours_until": round(hours_until, 1)},
            ))
            self._warned_1h.add(catalyst.name)
            log.info("1h warning for catalyst '%s'", catalyst.name)

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _load_state(self) -> None:
        """Load executed state from disk, merging with current catalyst list."""
        if not self._state_path.exists():
            return
        try:
            data = json.loads(self._state_path.read_text())
        except (json.JSONDecodeError, OSError) as e:
            log.warning("Failed to load catalyst state: %s", e)
            return

        executed_map: Dict[str, bool] = {}
        warned_6h: List[str] = data.get("warned_6h", [])
        warned_1h: List[str] = data.get("warned_1h", [])

        for entry in data.get("catalysts", []):
            key = f"{entry.get('name')}:{entry.get('event_date')}"
            executed_map[key] = entry.get("executed", False)

        for catalyst in self._catalysts:
            key = f"{catalyst.name}:{catalyst.event_date}"
            if key in executed_map:
                catalyst.executed = executed_map[key]

        self._warned_6h = set(warned_6h)
        self._warned_1h = set(warned_1h)
        log.info("Loaded catalyst state: %d entries", len(executed_map))

    def _save_state(self) -> None:
        """Persist executed state to disk."""
        data = {
            "updated_at": datetime.now(tz=timezone.utc).isoformat(),
            "catalysts": [
                {
                    "name": c.name,
                    "instrument": c.instrument,
                    "event_date": c.event_date,
                    "executed": c.executed,
                }
                for c in self._catalysts
            ],
            "warned_6h": list(self._warned_6h),
            "warned_1h": list(self._warned_1h),
        }
        try:
            self._state_path.write_text(json.dumps(data, indent=2) + "\n")
        except OSError as e:
            log.error("Failed to save catalyst state: %s", e)

    # ------------------------------------------------------------------
    # Convenience
    # ------------------------------------------------------------------

    @staticmethod
    def default_oil_catalysts() -> List[CatalystEvent]:
        """Current known oil catalysts — configure externally, this is a convenience."""
        return [
            CatalystEvent(
                name="trump_deadline",
                instrument="xyz:BRENTOIL",
                event_date="2026-04-06",
                pre_event_hours=24,
                reduce_size_pct=0.20,
                post_event_hours=12,
            ),
            CatalystEvent(
                name="contract_roll_bzm6_bzn6",
                instrument="xyz:BRENTOIL",
                event_date="2026-04-07",
                pre_event_hours=48,
                reduce_size_pct=0.30,
                post_event_hours=24,
            ),
        ]
