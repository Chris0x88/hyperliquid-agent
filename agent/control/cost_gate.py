"""Cost / token-budget gate for the agent runtime.

Enforces per-session and per-turn token budgets so a runaway agent loop
cannot generate surprise LLM bills.

CONTRACT references:
  - state.json fields: tokens_used_session, tokens_budget_session
  - Config: data/config/agent_cost_budget.json (kill-switch pattern)
  - AgentControl.abort() is called on hard-cap breach (best-effort import)

Budget defaults (all configurable via agent_cost_budget.json):
  - session_hard_cap:       200 000 tokens  → abort the run
  - session_warn_threshold: 150 000 tokens  → log warning, continue
  - per_turn_hard_cap:       50 000 tokens  → abort the turn / run
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

log = logging.getLogger("agent.cost_gate")

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
_CONFIG_PATH = _PROJECT_ROOT / "data" / "config" / "agent_cost_budget.json"

# ─────────────────────────────────────────────────────────────────────────────
# Data model
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class CostBudget:
    """Configurable token budget thresholds.

    All values are in tokens.  Load from config with ``CostBudget.from_config()``.
    """
    session_hard_cap: int = 200_000
    session_warn_threshold: int = 150_000
    per_turn_hard_cap: int = 50_000

    @classmethod
    def from_config(cls, config_path: Path | str | None = None) -> "CostBudget":
        """Load thresholds from JSON config, falling back to defaults on any error."""
        path = Path(config_path) if config_path is not None else _CONFIG_PATH
        try:
            with open(path, encoding="utf-8") as f:
                raw = json.load(f)
            return cls(
                session_hard_cap=int(raw.get("session_hard_cap", cls.session_hard_cap)),
                session_warn_threshold=int(raw.get("session_warn_threshold", cls.session_warn_threshold)),
                per_turn_hard_cap=int(raw.get("per_turn_hard_cap", cls.per_turn_hard_cap)),
            )
        except FileNotFoundError:
            log.debug("Cost budget config not found at %s — using defaults", path)
        except (json.JSONDecodeError, ValueError, TypeError) as exc:
            log.warning("Cost budget config parse error (%s) — using defaults: %s", path, exc)
        return cls()


# ─────────────────────────────────────────────────────────────────────────────
# Main gate class
# ─────────────────────────────────────────────────────────────────────────────

class CostGate:
    """Track token usage per session and enforce hard / soft budget limits.

    Usage::

        gate = CostGate()
        reason = gate.record_turn(prompt_tokens=1200, completion_tokens=400)
        if reason:
            # abort the agent run — budget exceeded
            ...

    The gate is intentionally stateless across process restarts (each new
    process is a new session).  Only per-session totals are tracked here;
    all-time cumulative spend is NOT tracked by this class.
    """

    def __init__(
        self,
        budget: Optional[CostBudget] = None,
        config_path: Path | str | None = None,
    ) -> None:
        self._budget = budget if budget is not None else CostBudget.from_config(config_path)
        self._tokens_used_session: int = 0
        self._warn_emitted: bool = False
        self._last_warning_at: Optional[int] = None  # tokens_used when warning fired

    # ── public interface ──────────────────────────────────────────────────────

    def record_turn(
        self,
        prompt_tokens: int,
        completion_tokens: int,
    ) -> Optional[str]:
        """Record token usage from one LLM call and check budget limits.

        Returns:
            ``None``     — budget is fine, agent may continue.
            ``str``      — reason string; caller should abort the agent run.

        Checks (in order):
        1. Per-turn hard cap  → immediate abort if a single call is too large.
        2. Session hard cap   → abort after accumulating the turn's tokens.
        3. Session soft warn  → log warning but return None (continue).
        """
        prompt_tokens = max(0, int(prompt_tokens))
        completion_tokens = max(0, int(completion_tokens))
        turn_total = prompt_tokens + completion_tokens

        # 1. Per-turn hard cap — check BEFORE accumulating
        if turn_total > self._budget.per_turn_hard_cap:
            reason = (
                f"per_turn_hard_cap exceeded: turn used {turn_total:,} tokens "
                f"(cap={self._budget.per_turn_hard_cap:,}). "
                "Possible context-bloat — aborting to prevent runaway spend."
            )
            log.error("CostGate ABORT — %s", reason)
            self._tokens_used_session += turn_total  # still record it
            return reason

        # Accumulate
        self._tokens_used_session += turn_total

        # 2. Session hard cap
        if self._tokens_used_session > self._budget.session_hard_cap:
            reason = (
                f"session_hard_cap exceeded: {self._tokens_used_session:,} tokens used "
                f"(cap={self._budget.session_hard_cap:,}). "
                "Aborting agent session to prevent unexpected LLM spend."
            )
            log.error("CostGate ABORT — %s", reason)
            return reason

        # 3. Session soft warning (log once per threshold crossing)
        if (
            not self._warn_emitted
            and self._tokens_used_session >= self._budget.session_warn_threshold
        ):
            self._warn_emitted = True
            self._last_warning_at = self._tokens_used_session
            log.warning(
                "CostGate WARNING — session tokens at %s/%s (%.0f%% of hard cap). "
                "Approaching budget limit.",
                f"{self._tokens_used_session:,}",
                f"{self._budget.session_hard_cap:,}",
                100.0 * self._tokens_used_session / self._budget.session_hard_cap,
            )

        return None

    def get_state(self) -> dict:
        """Return current gate state — suitable for merging into state.json.

        Keys mirror the CONTRACT state-file schema::

            {
                "tokens_used_session": 12345,
                "tokens_budget_session": 200000,
                "last_warning_at": 151000 | null,
            }
        """
        return {
            "tokens_used_session": self._tokens_used_session,
            "tokens_budget_session": self._budget.session_hard_cap,
            "last_warning_at": self._last_warning_at,
        }

    def reset_session(self) -> None:
        """Reset all per-session counters (call at session start)."""
        self._tokens_used_session = 0
        self._warn_emitted = False
        self._last_warning_at = None

    # ── convenience properties ────────────────────────────────────────────────

    @property
    def tokens_used(self) -> int:
        """Tokens used so far this session."""
        return self._tokens_used_session

    @property
    def budget(self) -> CostBudget:
        """The active budget configuration."""
        return self._budget
