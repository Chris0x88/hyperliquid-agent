"""Tool-call gate chain for the embedded agent.

Every tool call walks the chain before the tool function is invoked.
The first gate that returns a non-None GateDecision stops the chain —
its decision is final.

Built-in evaluation order
--------------------------
1. AbortGate         — blocks everything if the operator aborted the session.
2. AuthorityGate     — blocks position-touching tools on manual/off assets.
3. PathAllowlistGate — blocks edit_file on non-allowlisted paths.
4. ApprovalGate      — marks WRITE_TOOLS as requiring_approval (not blocking).
5. RateLimitGate     — global rate-limit: 30 calls / 60 s sliding window.

Import discipline
-----------------
- AgentControl is imported inside AbortGate.evaluate() to avoid load-time
  failures when the state directory doesn't exist yet.
- common.authority is imported inside AuthorityGate.evaluate() for the same
  reason; tests can monkeypatch the module-level reference.
"""
from __future__ import annotations

import logging
import time
from abc import ABC, abstractmethod
from collections import deque
from pathlib import Path
from typing import Deque, List, Optional

from .agent_control import GateDecision

log = logging.getLogger("tool_gates")

# ---------------------------------------------------------------------------
# Tools that touch positions — AuthorityGate checks these.
# ---------------------------------------------------------------------------
_POSITION_TOOLS = frozenset({
    "place_trade",
    "close_position",
    "set_sl",
    "set_tp",
    "update_thesis",
})

# ---------------------------------------------------------------------------
# Write tools that require human approval — ApprovalGate checks these.
# Must stay in sync with WRITE_TOOLS in agent/tools.py.
# ---------------------------------------------------------------------------
_WRITE_TOOLS = frozenset({
    "place_trade",
    "update_thesis",
    "close_position",
    "set_sl",
    "set_tp",
    "memory_write",
    "edit_file",
    "run_bash",
    "restart_daemon",
})

# ---------------------------------------------------------------------------
# edit_file allowlist (mirrored from agent/tool_functions.py).
# PathAllowlistGate uses this; the source of truth remains tool_functions.py —
# if you extend the allowlist there, extend it here too.
# ---------------------------------------------------------------------------
_EDIT_FILE_ALLOWLIST: tuple[str, ...] = (
    "agent/prompts/",
    "data/thesis/",
    "data/agent_memory/",
    "data/config/",
    "tests/",
    "docs/",
)

# ---------------------------------------------------------------------------
# Rate limit parameters
# ---------------------------------------------------------------------------
_RATE_LIMIT_MAX_CALLS: int = 30
_RATE_LIMIT_WINDOW_S: float = 60.0


# ═══════════════════════════════════════════════════════════════════════════
# Gate ABC
# ═══════════════════════════════════════════════════════════════════════════


class Gate(ABC):
    """Base class for a single gate in the chain.

    evaluate() returns:
    - None              — gate passes; chain continues to the next gate.
    - GateDecision      — chain stops; this decision is returned to the caller.
    """

    @abstractmethod
    def evaluate(
        self,
        tool_name: str,
        args: dict,
        ctx: dict,
    ) -> Optional[GateDecision]:
        ...


# ═══════════════════════════════════════════════════════════════════════════
# 1. AbortGate
# ═══════════════════════════════════════════════════════════════════════════


class AbortGate(Gate):
    """Block all tool calls if the operator has aborted the agent session.

    AgentControl is imported lazily so a missing state directory doesn't
    break module import.  Pass a pre-constructed AgentControl in tests.
    """

    def __init__(self, agent_control=None) -> None:
        self._ac = agent_control

    def _get_control(self):
        if self._ac is not None:
            return self._ac
        # Lazy import — avoids load-time failure when state dir is absent.
        try:
            from agent.control.agent_control import AgentControl
            return AgentControl()
        except Exception:
            return None

    def evaluate(
        self,
        tool_name: str,
        args: dict,
        ctx: dict,
    ) -> Optional[GateDecision]:
        control = self._get_control()
        if control is None:
            # Can't read abort state — fail open.
            return None
        try:
            aborted = control.is_aborted()
        except Exception as exc:
            log.warning("AbortGate: failed to read abort flag: %s", exc)
            return None
        if aborted:
            reason = "agent aborted by operator"
            log.warning("AbortGate: blocking %s — %s", tool_name, reason)
            return GateDecision(allow=False, block_reason=reason)
        return None


# ═══════════════════════════════════════════════════════════════════════════
# 2. AuthorityGate
# ═══════════════════════════════════════════════════════════════════════════


class AuthorityGate(Gate):
    """Block position-touching tools when the asset's authority is manual or off.

    The asset is extracted from the tool args:
    - place_trade / close_position / set_sl / set_tp → args["coin"]
    - update_thesis → args["market"]

    If the asset can't be determined (bad args), the gate passes.
    common.authority is imported lazily for the same reason as AbortGate.
    """

    def evaluate(
        self,
        tool_name: str,
        args: dict,
        ctx: dict,
    ) -> Optional[GateDecision]:
        if tool_name not in _POSITION_TOOLS:
            return None

        asset = _extract_asset(tool_name, args)
        if not asset:
            return None

        try:
            from common.authority import is_agent_managed
            managed = is_agent_managed(asset)
        except Exception as exc:
            log.warning("AuthorityGate: authority check failed for %s: %s", asset, exc)
            return None

        if not managed:
            reason = f"asset under manual authority: {asset}"
            log.warning(
                "AuthorityGate: blocking %s on %s — %s", tool_name, asset, reason
            )
            return GateDecision(allow=False, block_reason=reason)
        return None


def _extract_asset(tool_name: str, args: dict) -> Optional[str]:
    """Pull the coin/market identifier from tool args."""
    if tool_name == "update_thesis":
        return args.get("market")
    return args.get("coin")


# ═══════════════════════════════════════════════════════════════════════════
# 3. PathAllowlistGate
# ═══════════════════════════════════════════════════════════════════════════


class PathAllowlistGate(Gate):
    """Enforce the edit_file path allowlist.

    If the requested path is outside the allowlist AND allow_unsafe is not
    True in the args, block with a clear reason.

    The allowlist is checked using the same normalisation logic as
    agent/tool_functions.py: the path is made project-relative first.
    """

    def __init__(
        self,
        allowlist: tuple[str, ...] = _EDIT_FILE_ALLOWLIST,
        project_root: Optional[Path] = None,
    ) -> None:
        self._allowlist = allowlist
        self._project_root = project_root or Path(__file__).resolve().parent.parent.parent

    def evaluate(
        self,
        tool_name: str,
        args: dict,
        ctx: dict,
    ) -> Optional[GateDecision]:
        if tool_name != "edit_file":
            return None

        allow_unsafe = bool(args.get("allow_unsafe", False))
        if allow_unsafe:
            # Caller explicitly requested unsafe — let tool_functions handle it.
            return None

        path_str = args.get("path", "")
        if not path_str:
            return None

        # Normalise to project-relative path (same logic as tool_functions.py)
        try:
            target = (self._project_root / path_str).resolve()
            rel = str(target.relative_to(self._project_root))
        except (ValueError, OSError):
            # Path outside project root entirely — block it.
            reason = f"edit_file path outside project root: {path_str}"
            log.warning("PathAllowlistGate: blocking — %s", reason)
            return GateDecision(allow=False, block_reason=reason)

        is_allowed = any(rel.startswith(prefix) for prefix in self._allowlist)
        if not is_allowed:
            reason = (
                f"edit_file path not in allowlist: {path_str}. "
                f"Pass allow_unsafe=True only when explicitly authorised."
            )
            log.warning("PathAllowlistGate: blocking — %s", reason)
            return GateDecision(allow=False, block_reason=reason)

        return None


# ═══════════════════════════════════════════════════════════════════════════
# 4. ApprovalGate
# ═══════════════════════════════════════════════════════════════════════════


class ApprovalGate(Gate):
    """Mark WRITE_TOOLS as requiring approval before execution.

    This gate does NOT block — it sets requires_approval=True so the
    runtime can suspend the tool, send the Telegram confirmation, and
    resume only after the operator approves.  The existing approval flow
    in telegram/approval.py is unchanged.
    """

    def __init__(self, write_tools: frozenset = _WRITE_TOOLS) -> None:
        self._write_tools = write_tools

    def evaluate(
        self,
        tool_name: str,
        args: dict,
        ctx: dict,
    ) -> Optional[GateDecision]:
        if tool_name in self._write_tools:
            log.debug("ApprovalGate: %s requires approval", tool_name)
            return GateDecision(allow=True, requires_approval=True)
        return None


# ═══════════════════════════════════════════════════════════════════════════
# 5. RateLimitGate
# ═══════════════════════════════════════════════════════════════════════════


class RateLimitGate(Gate):
    """Global sliding-window rate limit: max 30 tool calls per 60 s.

    Uses a deque of call timestamps.  On each evaluate() call a monotonic
    clock reading is pushed; entries older than the window are evicted first.
    Thread-safety is NOT guaranteed — the agent runs single-threaded within
    a turn, so this is acceptable.  If parallelism is ever added, wrap
    in a threading.Lock.

    A custom clock callable can be injected for deterministic testing.
    """

    def __init__(
        self,
        max_calls: int = _RATE_LIMIT_MAX_CALLS,
        window_s: float = _RATE_LIMIT_WINDOW_S,
        clock=None,
    ) -> None:
        self._max_calls = max_calls
        self._window_s = window_s
        self._clock = clock or time.monotonic
        self._timestamps: Deque[float] = deque()

    def evaluate(
        self,
        tool_name: str,
        args: dict,
        ctx: dict,
    ) -> Optional[GateDecision]:
        now = self._clock()
        cutoff = now - self._window_s

        # Evict stale entries
        while self._timestamps and self._timestamps[0] < cutoff:
            self._timestamps.popleft()

        if len(self._timestamps) >= self._max_calls:
            reason = (
                f"rate limit: {self._max_calls} calls/{int(self._window_s)}s exceeded"
            )
            log.warning("RateLimitGate: blocking %s — %s", tool_name, reason)
            return GateDecision(allow=False, block_reason=reason)

        # Record this call
        self._timestamps.append(now)
        return None


# ═══════════════════════════════════════════════════════════════════════════
# GateChain
# ═══════════════════════════════════════════════════════════════════════════


class GateChain:
    """Ordered list of gates.  First non-None decision wins."""

    def __init__(self, gates: List[Gate]) -> None:
        self._gates = list(gates)

    def evaluate(
        self,
        tool_name: str,
        args: dict,
        ctx: dict,
    ) -> GateDecision:
        """Walk the chain; return the first gate decision or allow-by-default."""
        for gate in self._gates:
            decision = gate.evaluate(tool_name, args, ctx)
            if decision is not None:
                return decision
        # No gate blocked or required approval — allow.
        return GateDecision(allow=True)


# ═══════════════════════════════════════════════════════════════════════════
# Module-level default chain (built once at import time)
# ═══════════════════════════════════════════════════════════════════════════


def default_gate_chain() -> GateChain:
    """Return a new GateChain with the 5 built-in gates in correct order."""
    return GateChain([
        AbortGate(),
        AuthorityGate(),
        PathAllowlistGate(),
        ApprovalGate(),
        RateLimitGate(),
    ])
