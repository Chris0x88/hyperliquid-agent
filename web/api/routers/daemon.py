"""Daemon state, iterators, tier control."""

from __future__ import annotations

import json
import os
import signal
import sys
from pathlib import Path

from fastapi import APIRouter
from pydantic import BaseModel

_project_root = Path(__file__).resolve().parent.parent.parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from daemon.tiers import TIER_ITERATORS, VALID_TIERS
from web.api.dependencies import DATA_DIR

router = APIRouter()


class TierUpdate(BaseModel):
    tier: str


class IteratorToggle(BaseModel):
    enabled: bool


@router.get("/state")
async def get_daemon_state():
    """Daemon state: tier, tick count, PID."""
    state_path = DATA_DIR / "daemon" / "state.json"
    pid_path = DATA_DIR / "daemon" / "daemon.pid"

    state = {}
    if state_path.exists():
        try:
            state = json.loads(state_path.read_text())
        except (json.JSONDecodeError, OSError):
            pass

    pid_alive = False
    pid = None
    if pid_path.exists():
        try:
            pid = int(pid_path.read_text().strip())
            os.kill(pid, 0)
            pid_alive = True
        except (ValueError, OSError):
            pass

    return {
        **state,
        "pid": pid,
        "pid_alive": pid_alive,
    }


@router.get("/iterators")
async def get_iterators():
    """List all iterators with their tier membership and enabled state."""
    config_dir = DATA_DIR / "config"
    iterators = []

    # Collect all unique iterator names
    all_names: set[str] = set()
    for tier_list in TIER_ITERATORS.values():
        all_names.update(tier_list)

    for name in sorted(all_names):
        # Determine which tiers include this iterator
        tiers = [t for t in VALID_TIERS if name in TIER_ITERATORS.get(t, [])]

        # Check config for enabled state
        config_path = config_dir / f"{name}.json"
        enabled = True
        if config_path.exists():
            try:
                cfg = json.loads(config_path.read_text())
                enabled = cfg.get("enabled", True)
            except (json.JSONDecodeError, OSError):
                pass

        iterators.append({
            "name": name,
            "tiers": tiers,
            "enabled": enabled,
            "has_config": config_path.exists(),
        })

    return {"iterators": iterators, "valid_tiers": VALID_TIERS}


@router.put("/iterators/{name}")
async def toggle_iterator(name: str, body: IteratorToggle):
    """Toggle an iterator's enabled state in its config file."""
    config_path = DATA_DIR / "config" / f"{name}.json"

    if config_path.exists():
        try:
            cfg = json.loads(config_path.read_text())
        except (json.JSONDecodeError, OSError):
            cfg = {}
    else:
        cfg = {}

    cfg["enabled"] = body.enabled

    tmp = config_path.with_suffix(".tmp")
    tmp.write_text(json.dumps(cfg, indent=2))
    tmp.replace(config_path)

    return {"name": name, "enabled": body.enabled}


@router.get("/tier")
async def get_tier():
    """Current daemon tier."""
    state_path = DATA_DIR / "daemon" / "state.json"
    if state_path.exists():
        try:
            state = json.loads(state_path.read_text())
            return {"tier": state.get("tier", "watch")}
        except (json.JSONDecodeError, OSError):
            pass
    return {"tier": "watch"}


@router.post("/restart")
async def restart_daemon():
    """Send SIGTERM to daemon PID for graceful restart (launchd will respawn)."""
    pid_path = DATA_DIR / "daemon" / "daemon.pid"
    if not pid_path.exists():
        return {"status": "error", "message": "No daemon PID file found"}

    try:
        pid = int(pid_path.read_text().strip())
        os.kill(pid, signal.SIGTERM)
        return {"status": "ok", "message": f"SIGTERM sent to PID {pid}"}
    except (ValueError, OSError) as e:
        return {"status": "error", "message": str(e)}
