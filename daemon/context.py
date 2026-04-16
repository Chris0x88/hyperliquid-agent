"""Shared data structures for the daemon tick loop."""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Dict, List, Optional, Protocol

from exchange.position_tracker import Position
from exchange.risk_manager import RiskGate

# ThesisState imported lazily to avoid circular imports — use Any type hint here


import enum


class OrderState(enum.Enum):
    """Nautilus-inspired order state tracking.

    Minimal FSM: tracks order from approval through execution.
    Terminal states: FILLED, REJECTED, CANCELLED, EXPIRED.
    """
    PENDING_APPROVAL = "pending_approval"
    SUBMITTED = "submitted"
    ACCEPTED = "accepted"
    FILLED = "filled"
    REJECTED = "rejected"
    CANCELLED = "cancelled"
    EXPIRED = "expired"

    @property
    def is_terminal(self) -> bool:
        return self in (OrderState.FILLED, OrderState.REJECTED,
                        OrderState.CANCELLED, OrderState.EXPIRED)


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
    # Order lifecycle tracking (Nautilus-inspired)
    state: OrderState = OrderState.SUBMITTED
    submitted_at: float = 0.0  # time.time()
    oid: str = ""              # exchange order ID once accepted


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
    daemon_tier: str = "watch"

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

    # Total equity snapshot (BUG-FIX 2026-04-08, additive).
    #
    # ``ctx.balances["USDC"]`` has always been native-perps-only because
    # connector.py reads from the native HL ``get_account_state()`` endpoint
    # and never sums xyz margin or spot USDC. Consumers that report "equity"
    # to the operator (TelegramIterator periodic alerts, JournalIterator
    # trade records, account_collector drawdown alerts) need the SAME total
    # the ``/status`` Telegram command reports — which is
    # native + xyz + spot USDC (see cli/daemon/CLAUDE.md).
    #
    # Rather than change the semantics of ``ctx.balances["USDC"]`` and risk
    # disturbing ``execution_engine`` sizing math mid-session, we add this
    # parallel field. ConnectorIterator populates it on every tick by summing
    # the three sources; any alerting iterator should prefer this over
    # ``ctx.balances["USDC"]`` when reporting equity numbers to the user.
    #
    # Value of 0.0 means the connector has not yet populated it (tick 0 or
    # adapter unavailable) — callers should fall back to ``ctx.balances``
    # in that case.
    total_equity: float = 0.0

    # Latest signal outputs (populated by pulse + radar iterators on each scan).
    # Consumed by apex_advisor (C3 — dry-run advisor) so APEX can run on the
    # same in-memory tick rather than re-reading data/research/signals.jsonl.
    # Each list is a snapshot of the most recent scan; iterators that produce
    # them update on their own scan cadence (pulse=2min, radar=5min) and the
    # lists may stay populated across multiple ticks until the next scan.
    pulse_signals: List[Dict[str, Any]] = field(default_factory=list)
    radar_opportunities: List[Dict[str, Any]] = field(default_factory=list)


class Iterator(Protocol):
    """Protocol for daemon iterators."""
    name: str

    def tick(self, ctx: TickContext) -> None: ...

    def on_start(self, ctx: TickContext) -> None: ...

    def on_stop(self) -> None: ...
