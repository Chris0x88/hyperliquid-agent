"""Shared data structures for the daemon tick loop."""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Dict, List, Optional, Protocol

from parent.position_tracker import Position
from parent.risk_manager import RiskGate

# ThesisState imported lazily to avoid circular imports — use Any type hint here


@dataclass
class OrderIntent:
    """Order queued by an iterator for post-tick execution.

    RebalancerIterator converts StrategyDecision into OrderIntent.
    """
    strategy_name: str
    instrument: str
    action: str              # "buy" | "sell" | "close" | "noop"
    size: Decimal
    price: Optional[Decimal] = None  # None = market order
    reduce_only: bool = False
    order_type: str = "Gtc"
    meta: Dict[str, Any] = field(default_factory=dict)


@dataclass
class Alert:
    """Notification for logging and OpenClaw consumption."""
    severity: str            # "info" | "warning" | "critical"
    source: str              # iterator name
    message: str
    timestamp: int = 0
    data: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = int(time.time() * 1000)


@dataclass
class DataRequirements:
    """What market data a strategy needs each tick."""
    instruments: List[str] = field(default_factory=list)
    candle_intervals: List[str] = field(default_factory=lambda: ["1h"])
    candle_lookback_ms: int = 86_400_000  # 24h default


@dataclass
class StrategySlot:
    """One active strategy in the daemon roster."""
    name: str
    strategy_path: str       # e.g. "strategies.power_law_btc:PowerLawBTCStrategy"
    instrument: str
    tick_interval: int       # seconds between strategy ticks
    last_tick: int = 0       # timestamp of last execution
    paused: bool = False
    params: Dict[str, Any] = field(default_factory=dict)
    data_reqs: DataRequirements = field(default_factory=DataRequirements)

    # Runtime only (not serialized)
    strategy: Any = field(default=None, repr=False)


@dataclass
class TickContext:
    """Shared data bag populated by ConnectorIterator, consumed by all others."""

    # Clock metadata
    timestamp: int = 0
    tick_number: int = 0

    # Market data (populated by ConnectorIterator)
    balances: Dict[str, Decimal] = field(default_factory=dict)
    positions: List[Position] = field(default_factory=list)
    prices: Dict[str, Decimal] = field(default_factory=dict)
    candles: Dict[str, Dict[str, list]] = field(default_factory=dict)  # instrument → interval → candles
    all_markets: List[Dict] = field(default_factory=list)

    # Downstream outputs
    order_queue: List[OrderIntent] = field(default_factory=list)
    alerts: List[Alert] = field(default_factory=list)
    risk_gate: RiskGate = RiskGate.OPEN

    # Roster (set by Clock before tick)
    active_strategies: Dict[str, StrategySlot] = field(default_factory=dict)

    # Pre-computed market structure snapshots (populated by MarketStructureIterator)
    market_snapshots: Dict[str, Any] = field(default_factory=dict)  # market -> MarketSnapshot

    # Two-layer architecture: thesis state from AI (written by scheduled task)
    thesis_states: Dict[str, Any] = field(default_factory=dict)  # market -> ThesisState

    # Account collector outputs
    snapshot_ref: str = ""              # filename of current account snapshot
    account_drawdown_pct: float = 0.0   # current drawdown from high water mark
    high_water_mark: float = 0.0        # peak account equity observed


class Iterator(Protocol):
    """Protocol for daemon iterators."""
    name: str

    def tick(self, ctx: TickContext) -> None: ...

    def on_start(self, ctx: TickContext) -> None: ...

    def on_stop(self) -> None: ...
