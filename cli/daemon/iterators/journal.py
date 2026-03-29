"""JournalIterator — logs state snapshots and PnL each tick."""
from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Optional

from cli.daemon.context import TickContext

log = logging.getLogger("daemon.journal")


class JournalIterator:
    name = "journal"

    def __init__(self, data_dir: str = "data/daemon"):
        self._journal_dir = Path(data_dir) / "journal"
        self._trades_path = Path(data_dir) / "trades.jsonl"

    def on_start(self, ctx: TickContext) -> None:
        self._journal_dir.mkdir(parents=True, exist_ok=True)
        log.info("JournalIterator started")

    def on_stop(self) -> None:
        pass

    def tick(self, ctx: TickContext) -> None:
        # Log a snapshot every tick
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

        # Write to journal file (append, one line per tick)
        journal_file = self._journal_dir / "ticks.jsonl"
        with open(journal_file, "a") as f:
            f.write(json.dumps(snapshot) + "\n")
