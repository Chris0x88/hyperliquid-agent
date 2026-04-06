"""JournalIterator — logs state snapshots, detects position closes, writes trade journal.

Tracks positions across ticks. When a position disappears (closed) or flips direction,
creates a full JournalEntry with entry/exit/SL/TP/PnL and persists via JournalGuard.
"""
from __future__ import annotations

import json
import logging
import time
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, List, Optional

from cli.daemon.context import TickContext

log = logging.getLogger("daemon.journal")

ZERO = Decimal("0")
JOURNAL_JSONL = "data/research/journal.jsonl"


class JournalIterator:
    name = "journal"

    def __init__(self, data_dir: str = "data/daemon"):
        self._journal_dir = Path(data_dir) / "journal"
        self._trades_dir = Path("data/research/trades")
        self._journal_jsonl = Path(JOURNAL_JSONL)
        # Position tracking across ticks
        self._prev_positions: Dict[str, _TrackedPosition] = {}
        self._trade_counter = 0

    def on_start(self, ctx: TickContext) -> None:
        self._journal_dir.mkdir(parents=True, exist_ok=True)
        self._trades_dir.mkdir(parents=True, exist_ok=True)
        self._journal_jsonl.parent.mkdir(parents=True, exist_ok=True)
        # Count existing trades for numbering
        existing = list(self._trades_dir.glob("*.json"))
        self._trade_counter = len(existing)
        log.info("JournalIterator started (existing trades: %d)", self._trade_counter)

    def on_stop(self) -> None:
        pass

    def tick(self, ctx: TickContext) -> None:
        # --- 1. Detect position changes ---
        self._detect_position_changes(ctx)

        # --- 2. Log tick snapshot (existing behavior) ---
        snapshot = {
            "timestamp": ctx.timestamp,
            "tick": ctx.tick_number,
            "balances": {k: str(v) for k, v in ctx.balances.items()},
            "prices": {k: str(v) for k, v in ctx.prices.items()},
            "risk_gate": ctx.risk_gate.value,
            "n_positions": len(ctx.positions),
            "n_alerts": len(ctx.alerts),
            "n_orders": len(ctx.order_queue),
            "strategies": {
                name: {"instrument": s.instrument, "paused": s.paused, "last_tick": s.last_tick}
                for name, s in ctx.active_strategies.items()
            },
        }

        journal_file = self._journal_dir / "ticks.jsonl"
        with open(journal_file, "a") as f:
            f.write(json.dumps(snapshot) + "\n")

    def _detect_position_changes(self, ctx: TickContext) -> None:
        """Compare current positions to previous tick. Log closed trades."""
        current: Dict[str, _TrackedPosition] = {}

        for pos in ctx.positions:
            if pos.net_qty == ZERO:
                continue
            instrument = pos.instrument
            # Normalize key for comparison
            key = instrument.replace("xyz:", "").upper()
            price = float(ctx.prices.get(instrument, ZERO))
            current[key] = _TrackedPosition(
                instrument=instrument,
                net_qty=float(pos.net_qty),
                avg_entry_price=float(pos.avg_entry_price),
                leverage=float(pos.leverage) if pos.leverage else 0,
                liquidation_price=float(pos.liquidation_price) if pos.liquidation_price else 0,
                current_price=price,
                timestamp=ctx.timestamp,
            )

        # Check for positions that were open last tick but gone now (CLOSED)
        for key, prev in self._prev_positions.items():
            if key not in current:
                # Position closed — log it
                exit_price = float(ctx.prices.get(prev.instrument, ZERO))
                if exit_price <= 0:
                    # Try without prefix
                    for k, v in ctx.prices.items():
                        if k.replace("xyz:", "").upper() == key:
                            exit_price = float(v)
                            break

                self._log_closed_trade(prev, exit_price, ctx)

        # Check for direction flips (rare but important)
        for key, curr in current.items():
            prev = self._prev_positions.get(key)
            if prev and _direction_flipped(prev.net_qty, curr.net_qty):
                # Old direction closed, new direction opened
                exit_price = curr.current_price
                self._log_closed_trade(prev, exit_price, ctx)

        self._prev_positions = current

    def _log_closed_trade(self, prev: _TrackedPosition, exit_price: float, ctx: TickContext) -> None:
        """Write a full trade record when a position is closed."""
        entry_price = prev.avg_entry_price
        direction = "LONG" if prev.net_qty > 0 else "SHORT"
        size = abs(prev.net_qty)

        # Compute PnL
        if direction == "LONG":
            pnl = (exit_price - entry_price) * size
        else:
            pnl = (entry_price - exit_price) * size

        notional = entry_price * size
        roe_pct = (pnl / notional * 100) if notional > 0 else 0

        # Find any SL/TP orders that were active for this instrument
        sl_price, tp_price = self._find_sl_tp(prev.instrument, ctx)

        # Get thesis context if available
        thesis_summary = ""
        conviction = 0.0
        thesis_key = prev.instrument
        if thesis_key in ctx.thesis_states:
            thesis = ctx.thesis_states[thesis_key]
            thesis_summary = getattr(thesis, "thesis_summary", "")
            conviction = getattr(thesis, "conviction", 0.0)

        self._trade_counter += 1
        now = time.strftime("%Y%m%d", time.gmtime())
        coin = prev.instrument.replace("xyz:", "").lower()
        trade_id = f"{self._trade_counter:03d}"
        filename = f"{trade_id}-{coin}-{direction.lower()}-{now}.json"

        record = {
            "trade_id": trade_id,
            "timestamp_open": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(prev.timestamp / 1000)) if prev.timestamp > 1e9 else "",
            "timestamp_close": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "instrument": prev.instrument,
            "direction": direction,
            "size": round(size, 6),
            "entry_price": round(entry_price, 4),
            "exit_price": round(exit_price, 4),
            "pnl": round(pnl, 4),
            "roe_pct": round(roe_pct, 2),
            "leverage": prev.leverage,
            "liquidation_price": prev.liquidation_price,
            "stop_loss": sl_price,
            "take_profit": tp_price,
            "thesis_summary": thesis_summary,
            "conviction_at_close": conviction,
            "account_equity": float(ctx.balances.get("USDC", ZERO)),
        }

        # Write individual trade file
        trade_path = self._trades_dir / filename
        try:
            with open(trade_path, "w") as f:
                json.dump(record, f, indent=2)
        except Exception as e:
            log.error("Failed to write trade file %s: %s", filename, e)

        # Append to journal JSONL (for ReflectEngine and AI agent)
        try:
            with open(self._journal_jsonl, "a") as f:
                f.write(json.dumps(record) + "\n")
        except Exception as e:
            log.error("Failed to append journal JSONL: %s", e)

        pnl_str = f"+${pnl:.2f}" if pnl >= 0 else f"-${abs(pnl):.2f}"
        log.info(
            "TRADE CLOSED: %s %s %.4f @ $%.2f → $%.2f  PnL=%s (%.1f%%)  SL=$%s TP=$%s",
            direction, prev.instrument, size, entry_price, exit_price,
            pnl_str, roe_pct, sl_price or "none", tp_price or "none",
        )

        # Alert for Telegram
        from cli.daemon.context import Alert
        ctx.alerts.append(Alert(
            severity="info",
            source=self.name,
            message=(
                f"Trade closed: {direction} {prev.instrument} "
                f"entry=${entry_price:.2f} exit=${exit_price:.2f} "
                f"PnL={pnl_str} ({roe_pct:+.1f}%)"
            ),
            data=record,
        ))

    def _find_sl_tp(self, instrument: str, ctx: TickContext) -> tuple:
        """Find SL and TP prices from open orders for this instrument."""
        sl_price = None
        tp_price = None
        # Orders in ctx don't have SL/TP distinction easily,
        # but we can check the order_queue meta or look at stored orders
        # For now, return None — this will be populated from exchange data
        # when we have it in the context
        return sl_price, tp_price


class _TrackedPosition:
    """Lightweight position snapshot for change detection."""
    __slots__ = ("instrument", "net_qty", "avg_entry_price", "leverage",
                 "liquidation_price", "current_price", "timestamp")

    def __init__(self, instrument: str, net_qty: float, avg_entry_price: float,
                 leverage: float, liquidation_price: float, current_price: float,
                 timestamp: int):
        self.instrument = instrument
        self.net_qty = net_qty
        self.avg_entry_price = avg_entry_price
        self.leverage = leverage
        self.liquidation_price = liquidation_price
        self.current_price = current_price
        self.timestamp = timestamp


def _direction_flipped(old_qty: float, new_qty: float) -> bool:
    """True if position flipped from long to short or vice versa."""
    return (old_qty > 0 and new_qty < 0) or (old_qty < 0 and new_qty > 0)
