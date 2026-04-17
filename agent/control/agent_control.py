"""AgentControl — runtime abort/steer surface for the embedded agent.

Implements the state-file contract from agent/control/CONTRACT.md.
The state file (data/agent/state.json) is written atomically on every
transition so it is always parseable JSON even across crashes.

Design notes
------------
- All mutations are protected by a single RLock so the Telegram bot thread
  and the runtime loop thread can share one instance safely.
- In-memory state is the authoritative source of truth; the disk file is
  a projection written after every mutation for cross-process visibility.
- Queue bounds: both queues are capped at _QUEUE_MAX (10) items.  When full
  the OLDEST item is evicted (not the new one), so the queue always holds
  the most recent operator intent.
"""
from __future__ import annotations

import threading
import time
import uuid
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

from .state_writer import atomic_write_json, read_state_json

# ---------------------------------------------------------------------------
# Re-export GateDecision so callers can do:
#   from agent.control import GateDecision
# ---------------------------------------------------------------------------
from dataclasses import dataclass as _dc


@_dc
class GateDecision:
    """Decision returned by a gate or by GateChain.evaluate().

    allow           — False means the tool call is blocked.
    block_reason    — Human-readable reason string (set when allow=False).
    requires_approval — True means the tool must go through the approval flow
                        before execution.
    transformed_args — If not None, replace the original args with these
                        before calling the tool function.
    """
    allow: bool
    block_reason: Optional[str] = None
    requires_approval: bool = False
    transformed_args: Optional[dict] = None


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

_DEFAULT_STATE_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "agent" / "state.json"
_QUEUE_MAX: int = 10              # max items in each queue (oldest evicted when full)
_DEFAULT_TURN_TIMEOUT: int = 60   # seconds


# ---------------------------------------------------------------------------
# AgentControl
# ---------------------------------------------------------------------------

class AgentControl:
    """Runtime controls: abort, steer, follow-up.

    Thread-safety: all mutations protected by a single RLock so the Telegram
    handler thread and the runtime loop can share one instance safely.

    State file: data/agent/state.json — written atomically on every transition.
    Both the Telegram bot and any dashboard process read this file for
    cross-process visibility.

    Typical lifecycle
    -----------------
    1. Telegram calls /stop  → abort("user_requested")
    2. Runtime loop checks is_aborted() at next LLM or tool boundary
    3. Loop exits cleanly; set_state(is_running=False) is written
    4. Telegram calls /agentstate → get_state() returns the final snapshot

    Queue draining
    --------------
    drain_steering_queue()  — called BEFORE each LLM turn; injects messages
    pop_follow_up()         — called AFTER the loop would otherwise end; runs
                              one more prompt if queue is non-empty
    """

    def __init__(
        self,
        state_path: Optional[Path] = None,
        session_id: Optional[str] = None,
        turn_timeout_s: int = _DEFAULT_TURN_TIMEOUT,
        tokens_budget_session: int = 200_000,
    ) -> None:
        self._lock = threading.RLock()
        self._path: Path = Path(state_path) if state_path else _DEFAULT_STATE_PATH

        # ---- identifiers ----
        self._session_id: str = session_id or str(uuid.uuid4())

        # ---- abort ----
        self._abort_flag: bool = False
        self._abort_reason: Optional[str] = None

        # ---- queues ----
        self._steering_queue: deque[dict] = deque()
        self._follow_up_queue: deque[dict] = deque()

        # ---- runtime state (mirrors state-file fields) ----
        self._is_running: bool = False
        self._started_at: Optional[str] = None
        self._current_turn: int = 0
        self._current_tool: Optional[dict] = None
        self._tokens_used: int = 0
        self._tokens_budget: int = tokens_budget_session
        self._turn_timeout_s: int = turn_timeout_s
        self._last_event: dict = {}

        # Write an initial state file so readers always find a valid document
        self._flush()

    # -----------------------------------------------------------------------
    # Abort control
    # -----------------------------------------------------------------------

    def abort(self, reason: str = "user_requested") -> None:
        """Signal the runtime to stop at the next boundary check.

        Does NOT interrupt a tool already mid-execution — the tool runs to
        completion and then the boundary check fires before the next LLM call.
        """
        with self._lock:
            self._abort_flag = True
            self._abort_reason = reason
            self._last_event = {
                "type": "abort",
                "ts": _iso_now(),
                "data": {"reason": reason},
            }
        self._flush()

    def is_aborted(self) -> bool:
        """True if the abort flag has been raised by the operator.

        Checked at every LLM-call boundary AND every tool-call boundary.
        Never auto-clears — a new session must construct a new AgentControl.
        """
        with self._lock:
            return self._abort_flag

    # -----------------------------------------------------------------------
    # Steering queue
    # -----------------------------------------------------------------------

    def steer(self, message: str) -> None:
        """Enqueue a steering message for injection before the next LLM turn.

        If the queue is already at capacity (_QUEUE_MAX), the oldest item is
        evicted to make room — the most recent operator intent always wins.
        """
        with self._lock:
            if len(self._steering_queue) >= _QUEUE_MAX:
                self._steering_queue.popleft()   # evict oldest
            self._steering_queue.append({"text": message, "queued_at": _iso_now()})
            self._last_event = {
                "type": "steer",
                "ts": _iso_now(),
                "data": {"message": message},
            }
        self._flush()

    def drain_steering_queue(self) -> List[dict]:
        """Pop ALL pending steering messages (FIFO) and clear the queue.

        Called by the runtime BEFORE each LLM turn.  Returned messages are
        injected as user-role messages into the conversation.
        """
        with self._lock:
            msgs = list(self._steering_queue)
            self._steering_queue.clear()
            if msgs:
                self._last_event = {
                    "type": "steering_drained",
                    "ts": _iso_now(),
                    "data": {"count": len(msgs)},
                }
        if msgs:
            self._flush()
        return msgs

    def clear_steering_queue(self) -> None:
        with self._lock:
            self._steering_queue.clear()
            self._last_event = {"type": "steering_cleared", "ts": _iso_now(), "data": {}}
        self._flush()

    # -----------------------------------------------------------------------
    # Follow-up queue
    # -----------------------------------------------------------------------

    def follow_up(self, message: str) -> None:
        """Enqueue a follow-up prompt to run after the current turn ends.

        If the queue is already at capacity, the oldest item is evicted.
        """
        with self._lock:
            if len(self._follow_up_queue) >= _QUEUE_MAX:
                self._follow_up_queue.popleft()  # evict oldest
            self._follow_up_queue.append({"text": message, "queued_at": _iso_now()})
            self._last_event = {
                "type": "follow_up",
                "ts": _iso_now(),
                "data": {"message": message},
            }
        self._flush()

    def pop_follow_up(self) -> Optional[dict]:
        """Pop the OLDEST follow-up message.  Returns None when queue is empty.

        Called by the runtime when the agent loop would otherwise end.
        If non-None is returned, the caller must re-enter the agent loop
        using the returned message as the new prompt.
        """
        with self._lock:
            if not self._follow_up_queue:
                return None
            msg = self._follow_up_queue.popleft()
            self._last_event = {
                "type": "follow_up_popped",
                "ts": _iso_now(),
                "data": {"text": msg["text"]},
            }
        self._flush()
        return msg

    def clear_follow_up_queue(self) -> None:
        with self._lock:
            self._follow_up_queue.clear()
            self._last_event = {"type": "follow_up_cleared", "ts": _iso_now(), "data": {}}
        self._flush()

    # -----------------------------------------------------------------------
    # Combined clear
    # -----------------------------------------------------------------------

    def clear_all_queues(self) -> None:
        with self._lock:
            self._steering_queue.clear()
            self._follow_up_queue.clear()
            self._last_event = {"type": "all_queues_cleared", "ts": _iso_now(), "data": {}}
        self._flush()

    # -----------------------------------------------------------------------
    # State inspection / mutation
    # -----------------------------------------------------------------------

    def get_state(self) -> dict:
        """Return the full state dict (same schema as the JSON file)."""
        with self._lock:
            return self._build_state()

    def set_state(self, **kwargs: Any) -> None:
        """Update in-memory state fields and flush to disk atomically.

        Accepted keys (a subset of the CONTRACT.md schema):
          is_running, current_turn, current_tool, tokens_used_session,
          last_event, abort_flag, abort_reason, turn_timeout_s
        """
        with self._lock:
            if "is_running" in kwargs:
                self._is_running = bool(kwargs["is_running"])
                if self._is_running and self._started_at is None:
                    self._started_at = _iso_now()
            if "current_turn" in kwargs:
                self._current_turn = int(kwargs["current_turn"])
            if "current_tool" in kwargs:
                self._current_tool = kwargs["current_tool"]
            if "tokens_used_session" in kwargs:
                self._tokens_used = int(kwargs["tokens_used_session"])
            if "last_event" in kwargs:
                self._last_event = kwargs["last_event"]
            if "abort_flag" in kwargs:
                self._abort_flag = bool(kwargs["abort_flag"])
            if "abort_reason" in kwargs:
                self._abort_reason = kwargs["abort_reason"]
            if "turn_timeout_s" in kwargs:
                self._turn_timeout_s = int(kwargs["turn_timeout_s"])
        self._flush()

    # -----------------------------------------------------------------------
    # Internal helpers
    # -----------------------------------------------------------------------

    def _build_state(self) -> dict:
        """Assemble the full state dict — must be called under self._lock."""
        return {
            "is_running": self._is_running,
            "session_id": self._session_id,
            "started_at": self._started_at,
            "current_turn": self._current_turn,
            "current_tool": self._current_tool,
            "abort_flag": self._abort_flag,
            "abort_reason": self._abort_reason,
            "steering_queue": list(self._steering_queue),
            "follow_up_queue": list(self._follow_up_queue),
            "turn_timeout_s": self._turn_timeout_s,
            "tokens_used_session": self._tokens_used,
            "tokens_budget_session": self._tokens_budget,
            "last_event": self._last_event,
        }

    def _flush(self) -> None:
        """Write current state to disk atomically.  Never raises."""
        with self._lock:
            state = self._build_state()
        try:
            atomic_write_json(state, self._path)
        except Exception:
            # A disk write failure must never crash the runtime.
            pass


def _iso_now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
