"""hl status — show positions, PnL, risk state."""
from __future__ import annotations

import sys
import time
from decimal import Decimal
from pathlib import Path

import typer


def status_cmd(
    data_dir: str = typer.Option(
        "data/cli", "--data-dir",
        help="Directory where state is persisted",
    ),
    watch: bool = typer.Option(
        False, "--watch", "-w",
        help="Continuously refresh",
    ),
    interval: float = typer.Option(
        5.0, "--interval",
        help="Refresh interval when watching (seconds)",
    ),
):
    """Show positions, PnL, and risk state from persisted state."""
    project_root = str(Path(__file__).resolve().parent.parent.parent)
    if project_root not in sys.path:
        sys.path.insert(0, project_root)

    from exchange.store import StateDB, JSONLStore
    from exchange.position_tracker import PositionTracker
    from exchange.risk_manager import RiskManager
    from cli.display import status_table

    db = StateDB(path=f"{data_dir}/state.db")
    trades = JSONLStore(path=f"{data_dir}/trades.jsonl")

    def _render():
        tick_count = db.get("tick_count") or 0
        start_time_ms = db.get("start_time_ms") or 0
        strategy_id = db.get("strategy_id") or "unknown"
        instrument = db.get("instrument") or "unknown"
        order_stats = db.get("order_stats") or {}

        positions_data = db.get("positions")
        risk_data = db.get("risk")

        if positions_data is None:
            typer.echo("No state found. Is the engine running?")
            return

        tracker = PositionTracker.from_dict(positions_data)
        rm = RiskManager.from_dict(risk_data) if risk_data else RiskManager()

        # Get position for the agent
        agent_positions = positions_data.get("agents", {})
        pos_qty = 0.0
        avg_entry = 0.0
        notional = 0.0
        upnl = 0.0
        rpnl = 0.0

        for agent_id, instruments in agent_positions.items():
            for inst, pos_data in instruments.items():
                pos_qty = float(pos_data.get("net_qty", "0"))
                avg_entry = float(pos_data.get("avg_entry_price", "0"))
                notional = float(pos_data.get("notional", "0"))
                rpnl = float(pos_data.get("realized_pnl", "0"))
                if "unrealized_pnl" in pos_data:
                    upnl = float(pos_data["unrealized_pnl"])

        dd_pct = 0.0
        if risk_data and risk_data.get("state"):
            rs = risk_data["state"]
            tvl = float(risk_data.get("limits", {}).get("tvl", "100000"))
            dd = float(rs.get("daily_drawdown", "0"))
            dd_pct = (dd / tvl * 100) if tvl > 0 else 0.0

        recent = trades.read_all()[-5:] if trades.path.exists() else []

        output = status_table(
            strategy=strategy_id,
            instrument=instrument,
            network="testnet",
            tick_count=tick_count,
            start_time_ms=start_time_ms,
            pos_qty=pos_qty,
            avg_entry=avg_entry,
            notional=notional,
            upnl=upnl,
            rpnl=rpnl,
            drawdown_pct=dd_pct,
            reduce_only=rm.state.reduce_only,
            safe_mode=rm.state.safe_mode,
            total_orders=order_stats.get("total_placed", 0),
            total_fills=order_stats.get("total_filled", 0),
            recent_fills=recent,
        )
        if watch:
            print("\033[2J\033[H", end="")  # Clear screen
        print(output)

    if watch:
        try:
            while True:
                _render()
                time.sleep(interval)
        except KeyboardInterrupt:
            pass
    else:
        _render()

    db.close()
