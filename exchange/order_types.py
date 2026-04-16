"""Managed order types that track state across engine ticks."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from common.models import MarketSnapshot, StrategyDecision


@dataclass
class BracketOrder:
    """Entry + take-profit + stop-loss managed as a state machine."""

    order_id: str
    instrument: str
    direction: str          # "long" or "short"
    entry_price: float      # filled entry price
    entry_size: float
    take_profit_price: float
    stop_loss_price: float
    status: str = "active"  # "active", "tp_triggered", "sl_triggered", "closed"

    def on_tick(self, snapshot: MarketSnapshot) -> Optional[StrategyDecision]:
        """Check if TP or SL should trigger. Returns exit decision or None."""
        if self.status != "active":
            return None
        mid = snapshot.mid_price
        if mid <= 0:
            return None

        close_side = "sell" if self.direction == "long" else "buy"

        # Take profit
        if self.direction == "long" and mid >= self.take_profit_price:
            self.status = "tp_triggered"
            return StrategyDecision(
                action="place_order", instrument=self.instrument,
                side=close_side, size=self.entry_size, limit_price=mid,
                meta={"trigger": "take_profit", "bracket_id": self.order_id},
            )
        if self.direction == "short" and mid <= self.take_profit_price:
            self.status = "tp_triggered"
            return StrategyDecision(
                action="place_order", instrument=self.instrument,
                side=close_side, size=self.entry_size, limit_price=mid,
                meta={"trigger": "take_profit", "bracket_id": self.order_id},
            )

        # Stop loss
        if self.direction == "long" and mid <= self.stop_loss_price:
            self.status = "sl_triggered"
            return StrategyDecision(
                action="place_order", instrument=self.instrument,
                side=close_side, size=self.entry_size, limit_price=mid,
                meta={"trigger": "stop_loss", "bracket_id": self.order_id},
            )
        if self.direction == "short" and mid >= self.stop_loss_price:
            self.status = "sl_triggered"
            return StrategyDecision(
                action="place_order", instrument=self.instrument,
                side=close_side, size=self.entry_size, limit_price=mid,
                meta={"trigger": "stop_loss", "bracket_id": self.order_id},
            )

        return None


@dataclass
class ConditionalOrder:
    """Trigger a child order when price crosses a threshold."""

    order_id: str
    instrument: str
    trigger_price: float
    trigger_condition: str   # "above" or "below"
    child_side: str          # "buy" or "sell"
    child_size: float
    status: str = "pending"  # "pending", "triggered", "expired"
    expiry_ms: int = 0       # 0 = no expiry
    created_at_ms: int = 0

    def on_tick(self, snapshot: MarketSnapshot) -> Optional[StrategyDecision]:
        if self.status != "pending":
            return None
        mid = snapshot.mid_price
        if mid <= 0:
            return None

        # Check expiry
        if self.expiry_ms > 0 and snapshot.timestamp_ms > self.expiry_ms:
            self.status = "expired"
            return None

        triggered = False
        if self.trigger_condition == "above" and mid >= self.trigger_price:
            triggered = True
        elif self.trigger_condition == "below" and mid <= self.trigger_price:
            triggered = True

        if triggered:
            self.status = "triggered"
            return StrategyDecision(
                action="place_order", instrument=self.instrument,
                side=self.child_side, size=self.child_size, limit_price=mid,
                meta={"trigger": "conditional", "conditional_id": self.order_id},
            )
        return None


@dataclass
class PeggedOrder:
    """Tracks mid price with an offset, re-prices each tick."""

    order_id: str
    instrument: str
    side: str
    size: float
    offset_bps: float       # Positive = away from mid (e.g., 5 bps behind)
    status: str = "active"
    max_ticks: int = 0      # 0 = no limit
    ticks_elapsed: int = 0

    def on_tick(self, snapshot: MarketSnapshot) -> Optional[StrategyDecision]:
        if self.status != "active":
            return None

        self.ticks_elapsed += 1
        if self.max_ticks > 0 and self.ticks_elapsed > self.max_ticks:
            self.status = "expired"
            return None

        mid = snapshot.mid_price
        if mid <= 0:
            return None

        offset = mid * self.offset_bps / 10000
        if self.side == "buy":
            price = mid - offset   # Bid below mid
        else:
            price = mid + offset   # Ask above mid

        return StrategyDecision(
            action="place_order", instrument=self.instrument,
            side=self.side, size=self.size, limit_price=round(price, 6),
            meta={"trigger": "pegged", "pegged_id": self.order_id},
        )
