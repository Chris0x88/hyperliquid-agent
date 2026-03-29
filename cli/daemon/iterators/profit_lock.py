"""ProfitLockIterator — sweeps a percentage of realized profits to a safety vault.

Architecture:
  - Tracks realized PnL from closed trades
  - When cumulative unrealized profit hits a threshold, queues a reduce-only order
  - Logs profit lock events to data/daemon/profit_locks.jsonl
  - Configurable sweep percentage (default 25%)

Note: HyperLiquid doesn't support programmatic vault transfers yet.
Profit locking works by:
  1. Tracking accumulated profits
  2. When profit threshold hit, partially closing positions (taking profit)
  3. Logging the "locked" amount — user can manually transfer to vault
  4. Future: auto-transfer when HL API supports it
"""
from __future__ import annotations

import json
import logging
import time
from decimal import Decimal
from pathlib import Path
from typing import Optional

from cli.daemon.context import Alert, OrderIntent, TickContext

log = logging.getLogger("daemon.profit_lock")

ZERO = Decimal("0")


class ProfitLockIterator:
    """Tracks profits and takes partial profits to protect capital."""
    name = "profit_lock"

    def __init__(
        self,
        sweep_pct: float = 0.25,       # Lock 25% of profits
        min_profit_usd: float = 50.0,   # Don't bother below $50
        check_interval: int = 300,       # Check every 5 minutes
        data_dir: str = "data/daemon",
    ):
        self._sweep_pct = Decimal(str(sweep_pct))
        self._min_profit_usd = Decimal(str(min_profit_usd))
        self._check_interval = check_interval
        self._ledger_path = Path(data_dir) / "profit_locks.jsonl"
        self._last_check: int = 0
        self._locked_total: Decimal = ZERO
        self._last_equity: Decimal = ZERO  # Track starting equity for session profit calc
        self._session_locked: Decimal = ZERO

    def on_start(self, ctx: TickContext) -> None:
        self._ledger_path.parent.mkdir(parents=True, exist_ok=True)
        # Load historical locks
        if self._ledger_path.exists():
            for line in self._ledger_path.read_text().splitlines():
                try:
                    entry = json.loads(line)
                    self._locked_total += Decimal(str(entry.get("locked_usd", 0)))
                except (json.JSONDecodeError, KeyError):
                    pass
        log.info("ProfitLockIterator started — sweep=%s%%, total locked=$%.2f",
                 float(self._sweep_pct * 100), float(self._locked_total))

    def on_stop(self) -> None:
        pass

    def tick(self, ctx: TickContext) -> None:
        now_s = ctx.timestamp // 1000
        if now_s - self._last_check < self._check_interval:
            return
        self._last_check = now_s

        # Track starting equity on first tick
        equity = ctx.balances.get("USDC", ctx.balances.get("USD", ZERO))
        if self._last_equity == ZERO and equity > ZERO:
            self._last_equity = equity
            return

        if not ctx.positions:
            return

        # Calculate unrealized PnL across all positions
        total_unrealized = ZERO
        profitable_positions = []

        for pos in ctx.positions:
            price = ctx.prices.get(pos.instrument, ZERO)
            if price == ZERO:
                continue
            pnl = pos.total_pnl(price)
            if pnl > self._min_profit_usd:
                profitable_positions.append((pos, pnl, price))
                total_unrealized += pnl

        if total_unrealized <= self._min_profit_usd:
            return

        # Calculate how much to lock
        lock_amount = total_unrealized * self._sweep_pct

        # For each profitable position, queue a partial close to lock profits
        for pos, pnl, price in profitable_positions:
            # Close proportional share of this position's profit
            pos_share = pnl / total_unrealized
            close_size = abs(pos.net_qty) * self._sweep_pct * pos_share

            if close_size <= ZERO:
                continue

            # Queue reduce-only close
            action = "sell" if pos.net_qty > ZERO else "buy"
            ctx.order_queue.append(OrderIntent(
                strategy_name="profit_lock",
                instrument=pos.instrument,
                action=action,
                size=close_size,
                reduce_only=True,
                order_type="Ioc",
                meta={"reason": "profit_lock", "locked_pct": float(self._sweep_pct)},
            ))

            ctx.alerts.append(Alert(
                severity="info",
                source="profit_lock",
                message=f"Locking {float(self._sweep_pct)*100:.0f}% profit on {pos.instrument}: "
                        f"${float(pnl * self._sweep_pct * pos_share):,.2f}",
            ))

        # Log the lock event
        entry = {
            "timestamp": ctx.timestamp,
            "tick": ctx.tick_number,
            "total_unrealized": float(total_unrealized),
            "locked_usd": float(lock_amount),
            "locked_pct": float(self._sweep_pct),
            "positions_touched": len(profitable_positions),
            "cumulative_locked": float(self._locked_total + lock_amount),
        }
        with open(self._ledger_path, "a") as f:
            f.write(json.dumps(entry) + "\n")

        self._locked_total += lock_amount
        self._session_locked += lock_amount
        log.info("Profit lock: $%.2f locked (session: $%.2f, total: $%.2f)",
                 float(lock_amount), float(self._session_locked), float(self._locked_total))
