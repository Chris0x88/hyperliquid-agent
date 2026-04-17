"""Agent control endpoints — cross-process control via shared state file.

CONTRACT: agent/control/CONTRACT.md is the locked surface.

The web API (separate process from the agent daemon) writes atomic updates to
data/agent/state.json.  The daemon's AgentControl polls that file on every
check boundary and acts on abort_flag / queue entries.

Pattern:
  1.  Read state.json (or start with defaults if missing).
  2.  Merge the requested mutation.
  3.  Atomic-write back via tmp + rename to avoid partial reads.
  4.  Return {"ok": true}.

GET /api/agent/state is intentionally auth-free (read-only public status).
POST endpoints require Bearer auth (same pattern as account.py).
"""

from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from web.api.auth import verify_token
from web.api.dependencies import DATA_DIR

router = APIRouter()

# State file location — matches CONTRACT.md
_STATE_PATH: Path = DATA_DIR / "agent" / "state.json"

# Default state returned when the file is missing or unreadable
_DEFAULT_STATE: dict[str, Any] = {
    "is_running": False,
    "session_id": None,
}


# ── Helpers ────────────────────────────────────────────────────────────────────


def _read_state() -> dict[str, Any]:
    """Read state.json, returning defaults if missing or malformed."""
    try:
        if _STATE_PATH.exists():
            return json.loads(_STATE_PATH.read_text())
    except Exception:
        pass
    return dict(_DEFAULT_STATE)


def _write_state(state: dict[str, Any]) -> None:
    """Atomic write: write to a temp file then rename (POSIX atomic)."""
    _STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp_fd, tmp_path = tempfile.mkstemp(
        dir=_STATE_PATH.parent, prefix=".state_tmp_"
    )
    try:
        with os.fdopen(tmp_fd, "w") as f:
            json.dump(state, f, indent=2)
        os.replace(tmp_path, _STATE_PATH)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def _now_iso() -> str:
    return datetime.now(tz=timezone.utc).isoformat()


# ── Request bodies ─────────────────────────────────────────────────────────────


class AbortRequest(BaseModel):
    reason: str = "user_requested"


class SteerRequest(BaseModel):
    message: str


class FollowUpRequest(BaseModel):
    message: str


# ── Endpoints ──────────────────────────────────────────────────────────────────


@router.get("/state")
async def get_agent_state():
    """Return the parsed contents of data/agent/state.json.

    Returns the CONTRACT default {"is_running": false, "session_id": null}
    when the file is missing or unreadable.
    No auth required — this is read-only status.
    """
    return _read_state()


@router.post("/abort", dependencies=[Depends(verify_token)])
async def abort_agent(body: AbortRequest):
    """Set abort_flag=True in the state file.

    The daemon's AgentControl polls the file and respects abort_flag on its
    next check boundary.  This endpoint does NOT call AgentControl.abort()
    in-process (they run in separate processes).
    """
    state = _read_state()
    state["abort_flag"] = True
    state["abort_reason"] = body.reason
    _write_state(state)
    return {"ok": True, "abort_flag": True, "reason": body.reason}


@router.post("/steer", dependencies=[Depends(verify_token)])
async def steer_agent(body: SteerRequest):
    """Append a steering message to the steering_queue in the state file."""
    state = _read_state()
    queue: list[dict] = state.get("steering_queue") or []
    queue.append({"text": body.message, "queued_at": _now_iso()})
    state["steering_queue"] = queue
    _write_state(state)
    return {"ok": True, "queue_depth": len(queue)}


@router.post("/follow-up", dependencies=[Depends(verify_token)])
async def follow_up_agent(body: FollowUpRequest):
    """Append a follow-up message to the follow_up_queue in the state file."""
    state = _read_state()
    queue: list[dict] = state.get("follow_up_queue") or []
    queue.append({"text": body.message, "queued_at": _now_iso()})
    state["follow_up_queue"] = queue
    _write_state(state)
    return {"ok": True, "queue_depth": len(queue)}


@router.post("/clear-queues", dependencies=[Depends(verify_token)])
async def clear_queues():
    """Empty both steering_queue and follow_up_queue in the state file."""
    state = _read_state()
    state["steering_queue"] = []
    state["follow_up_queue"] = []
    _write_state(state)
    return {"ok": True, "steering_queue": [], "follow_up_queue": []}
