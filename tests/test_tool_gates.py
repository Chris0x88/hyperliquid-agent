"""Tests for the tool-call gate chain.

Covers CONTRACT.md requirements:
  - test_chain_passes_when_no_gate_blocks
  - test_abort_gate_blocks_when_agent_aborted
  - test_authority_gate_blocks_on_manual_asset
  - test_path_allowlist_gate_blocks_outside_allowed
  - test_path_allowlist_gate_passes_with_allow_unsafe
  - test_approval_gate_marks_requires_approval
  - test_rate_limit_gate_blocks_after_30_calls_per_minute
  - test_first_blocking_gate_wins

All tests work fully offline — no network, no exchange, no state files.
"""
from __future__ import annotations

from collections import deque
from pathlib import Path
from typing import Optional
from unittest.mock import MagicMock, patch

import pytest

from agent.control.agent_control import GateDecision
from agent.control.tool_gates import (
    AbortGate,
    ApprovalGate,
    AuthorityGate,
    GateChain,
    PathAllowlistGate,
    RateLimitGate,
    default_gate_chain,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _allow(
    allow: bool = True,
    block_reason: Optional[str] = None,
    requires_approval: bool = False,
    transformed_args: Optional[dict] = None,
) -> GateDecision:
    """Shorthand for constructing GateDecisions in expected-value assertions."""
    return GateDecision(
        allow=allow,
        block_reason=block_reason,
        requires_approval=requires_approval,
        transformed_args=transformed_args,
    )


def _read_call(tool: str = "live_price", args: dict | None = None) -> tuple:
    return (tool, args or {}, {})


def _write_call(tool: str = "place_trade", coin: str = "BTC") -> tuple:
    return (tool, {"coin": coin, "side": "buy", "size": 1.0}, {})


# ---------------------------------------------------------------------------
# GateChain core contract
# ---------------------------------------------------------------------------


class TestGateChainContract:
    """GateDecision dataclass and chain pass-through behaviour."""

    def test_gate_decision_defaults(self):
        d = GateDecision(allow=True)
        assert d.allow is True
        assert d.block_reason is None
        assert d.requires_approval is False
        assert d.transformed_args is None

    def test_gate_decision_blocked(self):
        d = GateDecision(allow=False, block_reason="test reason")
        assert d.allow is False
        assert d.block_reason == "test reason"

    def test_chain_passes_when_no_gate_blocks(self):
        """An empty chain returns allow=True with no block reason."""
        chain = GateChain(gates=[])
        result = chain.evaluate("live_price", {}, {})
        assert result.allow is True
        assert result.block_reason is None
        assert result.requires_approval is False

    def test_chain_passes_when_all_gates_return_none(self):
        """Gates returning None all let the chain through."""

        class PassGate:
            def evaluate(self, *a, **kw) -> None:
                return None

        chain = GateChain(gates=[PassGate(), PassGate()])
        result = chain.evaluate("read_file", {"path": "x"}, {})
        assert result.allow is True

    def test_first_blocking_gate_wins(self):
        """When abort AND authority both block, the first (abort) decision is used."""

        class AlwaysBlock:
            def __init__(self, reason: str):
                self._reason = reason

            def evaluate(self, *a, **kw) -> GateDecision:
                return GateDecision(allow=False, block_reason=self._reason)

        first = AlwaysBlock("first gate")
        second = AlwaysBlock("second gate")
        chain = GateChain(gates=[first, second])
        result = chain.evaluate("place_trade", {"coin": "BTC"}, {})
        assert result.allow is False
        assert result.block_reason == "first gate"

    def test_gate_after_block_not_evaluated(self):
        """Once a gate returns a decision, subsequent gates are skipped."""
        evaluated = []

        class RecordGate:
            def __init__(self, tag: str):
                self._tag = tag

            def evaluate(self, *a, **kw) -> None:
                evaluated.append(self._tag)
                return None

        class BlockGate:
            def evaluate(self, *a, **kw) -> GateDecision:
                evaluated.append("block")
                return GateDecision(allow=False, block_reason="stop here")

        chain = GateChain(gates=[RecordGate("before"), BlockGate(), RecordGate("after")])
        chain.evaluate("any_tool", {}, {})
        assert evaluated == ["before", "block"]


# ---------------------------------------------------------------------------
# AbortGate
# ---------------------------------------------------------------------------


class TestAbortGate:
    def _make_control(self, aborted: bool) -> MagicMock:
        ctrl = MagicMock()
        ctrl.is_aborted.return_value = aborted
        return ctrl

    def test_abort_gate_passes_when_not_aborted(self):
        gate = AbortGate(agent_control=self._make_control(False))
        result = gate.evaluate("live_price", {}, {})
        assert result is None

    def test_abort_gate_blocks_when_agent_aborted(self):
        """AbortGate blocks ALL tool calls when is_aborted() is True."""
        gate = AbortGate(agent_control=self._make_control(True))
        result = gate.evaluate("live_price", {}, {})
        assert result is not None
        assert result.allow is False
        assert "aborted" in result.block_reason.lower()

    def test_abort_gate_blocks_write_tool_when_aborted(self):
        gate = AbortGate(agent_control=self._make_control(True))
        result = gate.evaluate("place_trade", {"coin": "BTC"}, {})
        assert result is not None
        assert result.allow is False

    def test_abort_gate_fails_open_on_exception(self):
        """If is_aborted() raises, gate passes (fail-open) rather than breaking the loop."""
        ctrl = MagicMock()
        ctrl.is_aborted.side_effect = RuntimeError("disk error")
        gate = AbortGate(agent_control=ctrl)
        result = gate.evaluate("live_price", {}, {})
        assert result is None

    def test_abort_gate_fails_open_when_control_unavailable(self):
        """If AgentControl can't be constructed, gate passes."""
        gate = AbortGate(agent_control=None)
        # Patch the lazy import to fail
        with patch("agent.control.tool_gates.AbortGate._get_control", return_value=None):
            result = gate.evaluate("live_price", {}, {})
        assert result is None


# ---------------------------------------------------------------------------
# AuthorityGate
# ---------------------------------------------------------------------------


class TestAuthorityGate:
    def test_authority_gate_ignores_non_position_tools(self):
        gate = AuthorityGate()
        # market_brief is not a position tool — should pass regardless
        with patch("common.authority.is_agent_managed", return_value=False):
            result = gate.evaluate("market_brief", {"market": "BTC"}, {})
        assert result is None

    def test_authority_gate_passes_on_agent_managed_asset(self):
        gate = AuthorityGate()
        with patch("common.authority.is_agent_managed", return_value=True):
            result = gate.evaluate("place_trade", {"coin": "BTC", "side": "buy", "size": 1}, {})
        assert result is None

    def test_authority_gate_blocks_on_manual_asset(self):
        """place_trade on a manual-authority asset must be blocked."""
        gate = AuthorityGate()
        with patch("common.authority.is_agent_managed", return_value=False):
            result = gate.evaluate("place_trade", {"coin": "xyz:BRENTOIL", "side": "buy", "size": 1}, {})
        assert result is not None
        assert result.allow is False
        assert "manual authority" in result.block_reason.lower()
        assert "xyz:BRENTOIL" in result.block_reason

    def test_authority_gate_blocks_close_position_on_off_asset(self):
        gate = AuthorityGate()
        with patch("common.authority.is_agent_managed", return_value=False):
            result = gate.evaluate("close_position", {"coin": "GOLD", "side": "sell", "size": 1}, {})
        assert result is not None
        assert result.allow is False

    def test_authority_gate_extracts_market_from_update_thesis(self):
        gate = AuthorityGate()
        with patch("common.authority.is_agent_managed", return_value=False) as mock_fn:
            gate.evaluate("update_thesis", {"market": "xyz:GOLD", "direction": "long"}, {})
        mock_fn.assert_called_once_with("xyz:GOLD")

    def test_authority_gate_passes_when_asset_missing_from_args(self):
        """If the coin arg is absent, gate should pass (not crash)."""
        gate = AuthorityGate()
        with patch("common.authority.is_agent_managed", return_value=False):
            result = gate.evaluate("place_trade", {}, {})
        assert result is None

    def test_authority_gate_fails_open_on_import_error(self):
        """If common.authority can't be imported, gate fails open."""
        gate = AuthorityGate()
        with patch("agent.control.tool_gates.AuthorityGate.evaluate", wraps=gate.evaluate):
            with patch("common.authority.is_agent_managed", side_effect=ImportError("no module")):
                result = gate.evaluate("place_trade", {"coin": "BTC"}, {})
        assert result is None


# ---------------------------------------------------------------------------
# PathAllowlistGate
# ---------------------------------------------------------------------------


class TestPathAllowlistGate:
    def test_ignores_non_edit_file_tools(self):
        gate = PathAllowlistGate()
        result = gate.evaluate("read_file", {"path": "/etc/passwd"}, {})
        assert result is None

    def test_allowlisted_path_passes(self):
        gate = PathAllowlistGate()
        result = gate.evaluate("edit_file", {"path": "data/thesis/btc.json"}, {})
        assert result is None

    def test_path_allowlist_gate_blocks_outside_allowed(self):
        """edit_file on exchange/risk_manager.py (without allow_unsafe) must be blocked."""
        gate = PathAllowlistGate()
        result = gate.evaluate(
            "edit_file",
            {"path": "exchange/risk_manager.py", "old_str": "x", "new_str": "y"},
            {},
        )
        assert result is not None
        assert result.allow is False
        assert "allowlist" in result.block_reason.lower()

    def test_path_allowlist_gate_passes_with_allow_unsafe(self):
        """allow_unsafe=True bypasses the allowlist check."""
        gate = PathAllowlistGate()
        result = gate.evaluate(
            "edit_file",
            {
                "path": "exchange/risk_manager.py",
                "old_str": "x",
                "new_str": "y",
                "allow_unsafe": True,
            },
            {},
        )
        assert result is None

    def test_path_outside_project_root_is_blocked(self):
        gate = PathAllowlistGate()
        result = gate.evaluate(
            "edit_file",
            {"path": "../../../etc/passwd", "old_str": "x", "new_str": "y"},
            {},
        )
        assert result is not None
        assert result.allow is False

    def test_agent_prompts_path_passes(self):
        gate = PathAllowlistGate()
        result = gate.evaluate("edit_file", {"path": "agent/prompts/AGENT.md"}, {})
        assert result is None

    def test_tests_path_passes(self):
        gate = PathAllowlistGate()
        result = gate.evaluate("edit_file", {"path": "tests/test_something.py"}, {})
        assert result is None

    def test_trading_core_blocked_without_unsafe(self):
        gate = PathAllowlistGate()
        result = gate.evaluate("edit_file", {"path": "trading/heartbeat.py"}, {})
        assert result is not None
        assert result.allow is False


# ---------------------------------------------------------------------------
# ApprovalGate
# ---------------------------------------------------------------------------


class TestApprovalGate:
    def test_read_tool_passes_without_approval(self):
        gate = ApprovalGate()
        result = gate.evaluate("live_price", {}, {})
        assert result is None

    def test_approval_gate_marks_requires_approval(self):
        """place_trade must come back with requires_approval=True, allow=True."""
        gate = ApprovalGate()
        result = gate.evaluate("place_trade", {"coin": "BTC", "side": "buy", "size": 1}, {})
        assert result is not None
        assert result.allow is True
        assert result.requires_approval is True

    def test_all_write_tools_require_approval(self):
        write_tools = [
            "place_trade", "update_thesis", "close_position",
            "set_sl", "set_tp", "memory_write", "edit_file", "run_bash", "restart_daemon",
        ]
        gate = ApprovalGate()
        for tool in write_tools:
            result = gate.evaluate(tool, {}, {})
            assert result is not None, f"{tool} should require approval"
            assert result.requires_approval is True, f"{tool} should have requires_approval=True"
            assert result.allow is True, f"{tool} should not be blocked by approval gate"

    def test_custom_write_tools_set(self):
        gate = ApprovalGate(write_tools=frozenset({"custom_tool"}))
        assert gate.evaluate("custom_tool", {}, {}).requires_approval is True
        assert gate.evaluate("place_trade", {}, {}) is None


# ---------------------------------------------------------------------------
# RateLimitGate
# ---------------------------------------------------------------------------


class TestRateLimitGate:
    def _make_gate(self, max_calls: int = 30, window_s: float = 60.0):
        """Gate with a manual clock so tests are deterministic."""
        self._now = 0.0

        def clock():
            return self._now

        return RateLimitGate(max_calls=max_calls, window_s=window_s, clock=clock)

    def test_allows_calls_below_limit(self):
        gate = self._make_gate(max_calls=5)
        for _ in range(5):
            result = gate.evaluate("live_price", {}, {})
            assert result is None

    def test_rate_limit_gate_blocks_after_30_calls_per_minute(self):
        """After 30 calls in the same 60-second window the 31st must be blocked."""
        gate = self._make_gate(max_calls=30, window_s=60.0)
        self._now = 0.0  # freeze clock

        for i in range(30):
            result = gate.evaluate("live_price", {}, {})
            assert result is None, f"call {i+1} should pass"

        # 31st call — same window, clock not advanced
        result = gate.evaluate("live_price", {}, {})
        assert result is not None
        assert result.allow is False
        assert "rate limit" in result.block_reason.lower()
        assert "30" in result.block_reason
        assert "60" in result.block_reason

    def test_rate_limit_resets_after_window(self):
        """After the window rolls over, the counter resets."""
        gate = self._make_gate(max_calls=3, window_s=60.0)
        self._now = 0.0

        for _ in range(3):
            gate.evaluate("x", {}, {})

        # Blocked
        assert gate.evaluate("x", {}, {}).allow is False

        # Advance clock past window
        self._now = 61.0
        result = gate.evaluate("x", {}, {})
        assert result is None  # passes again

    def test_sliding_window_partial_eviction(self):
        """Only calls older than the window are evicted."""
        gate = self._make_gate(max_calls=3, window_s=10.0)
        self._now = 0.0
        gate.evaluate("x", {}, {})   # t=0
        self._now = 5.0
        gate.evaluate("x", {}, {})   # t=5
        self._now = 7.0
        gate.evaluate("x", {}, {})   # t=7  — now at 3 calls, maxed

        # At t=11, the t=0 call expires
        self._now = 11.0
        result = gate.evaluate("x", {}, {})
        assert result is None  # t=5 and t=7 still in window; t=0 evicted; we had 2, now 3

    def test_different_tools_share_same_counter(self):
        """The rate limit is global — all tool names counted together."""
        gate = self._make_gate(max_calls=3)
        self._now = 0.0
        gate.evaluate("tool_a", {}, {})
        gate.evaluate("tool_b", {}, {})
        gate.evaluate("tool_c", {}, {})
        result = gate.evaluate("tool_d", {}, {})
        assert result is not None
        assert result.allow is False


# ---------------------------------------------------------------------------
# Full chain integration
# ---------------------------------------------------------------------------


class TestDefaultChain:
    """Smoke-test the default_gate_chain() factory."""

    def test_default_chain_returns_gate_chain(self):
        chain = default_gate_chain()
        assert isinstance(chain, GateChain)

    def test_default_chain_has_five_gates(self):
        chain = default_gate_chain()
        assert len(chain._gates) == 5

    def test_default_chain_gate_order(self):
        chain = default_gate_chain()
        gate_types = [type(g).__name__ for g in chain._gates]
        assert gate_types == [
            "AbortGate",
            "AuthorityGate",
            "PathAllowlistGate",
            "ApprovalGate",
            "RateLimitGate",
        ]

    def test_default_chain_passes_read_tool(self):
        """A simple read tool should pass the full default chain."""
        chain = default_gate_chain()
        # Patch authority so it doesn't hit disk
        with patch("common.authority.is_agent_managed", return_value=True):
            # Patch AbortGate to be not-aborted
            ctrl = MagicMock()
            ctrl.is_aborted.return_value = False
            chain._gates[0]._ac = ctrl

            result = chain.evaluate("live_price", {"market": "BTC"}, {})
        assert result.allow is True

    def test_abort_wins_over_authority(self):
        """With abort set, AbortGate fires before AuthorityGate."""
        chain = default_gate_chain()
        ctrl = MagicMock()
        ctrl.is_aborted.return_value = True
        chain._gates[0]._ac = ctrl  # inject mock into AbortGate

        # Even if authority would also block, abort fires first
        with patch("common.authority.is_agent_managed", return_value=False):
            result = chain.evaluate("place_trade", {"coin": "BTC"}, {})

        assert result.allow is False
        assert "aborted" in result.block_reason.lower()
