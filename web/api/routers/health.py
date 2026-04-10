"""System health endpoint — daemon, PIDs, telemetry, error budgets."""

from __future__ import annotations

import os
import sys
from pathlib import Path

from fastapi import APIRouter

_project_root = Path(__file__).resolve().parent.parent.parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from common.tools import daemon_health
from web.api.dependencies import DATA_DIR, STATE_DIR
from web.api.readers.state_reader import FileStateReader

router = APIRouter()
_state = FileStateReader(DATA_DIR, STATE_DIR)


def _check_pid(pid_file: Path) -> dict:
    """Check if a PID file exists and the process is alive."""
    if not pid_file.exists():
        return {"running": False, "pid": None}
    try:
        pid = int(pid_file.read_text().strip())
        os.kill(pid, 0)  # signal 0 = check if alive
        return {"running": True, "pid": pid}
    except (ValueError, OSError):
        return {"running": False, "pid": None}


@router.get("/health")
async def get_health():
    """Comprehensive system health check."""
    daemon_pid = _check_pid(DATA_DIR / "daemon" / "daemon.pid")
    telegram_pid = _check_pid(DATA_DIR / "daemon" / "telegram_bot.pid")
    rebalancer_pid = _check_pid(DATA_DIR / "vault_rebalancer.pid")

    daemon_state = _state.read("daemon_state")
    telemetry = _state.read("telemetry")
    working_state = _state.read("working_state")

    # Get daemon_health from tools (wraps internal checks)
    try:
        tools_health = daemon_health()
    except Exception:
        tools_health = {"error": "Failed to read daemon health"}

    return {
        "processes": {
            "daemon": daemon_pid,
            "telegram_bot": telegram_pid,
            "vault_rebalancer": rebalancer_pid,
        },
        "daemon": {
            "tier": daemon_state.get("tier", "unknown"),
            "tick_count": daemon_state.get("tick_count", 0),
            "daily_pnl": daemon_state.get("daily_pnl", 0),
            "total_trades": daemon_state.get("total_trades", 0),
        },
        "telemetry": telemetry,
        "heartbeat": {
            "escalation_level": working_state.get("escalation_level", 0),
            "failure_count": working_state.get("failure_count", 0),
        },
        "tools_health": tools_health,
    }
