"""Tests for agent/control/cost_gate.py — token-budget enforcer.

Run:
    cd agent-cli && .venv/bin/python -m pytest tests/test_cost_gate.py -x -q
"""
from __future__ import annotations

import json
import logging
import tempfile
from pathlib import Path

import pytest


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _make_gate(
    session_hard_cap: int = 200_000,
    session_warn_threshold: int = 150_000,
    per_turn_hard_cap: int = 50_000,
):
    """Build a CostGate with explicit budget values (no file I/O)."""
    from agent.control.cost_gate import CostBudget, CostGate
    budget = CostBudget(
        session_hard_cap=session_hard_cap,
        session_warn_threshold=session_warn_threshold,
        per_turn_hard_cap=per_turn_hard_cap,
    )
    return CostGate(budget=budget)


# ─────────────────────────────────────────────────────────────────────────────
# Core behaviour tests
# ─────────────────────────────────────────────────────────────────────────────

class TestUnderBudget:
    def test_under_budget_returns_none(self):
        """Normal usage well under all caps → no abort signal."""
        gate = _make_gate()
        reason = gate.record_turn(prompt_tokens=1_000, completion_tokens=500)
        assert reason is None

    def test_multiple_turns_under_cap_all_none(self):
        gate = _make_gate(session_hard_cap=200_000)
        for _ in range(10):
            reason = gate.record_turn(prompt_tokens=5_000, completion_tokens=2_000)
            assert reason is None

    def test_tokens_accumulate_across_turns(self):
        gate = _make_gate()
        gate.record_turn(prompt_tokens=10_000, completion_tokens=5_000)
        gate.record_turn(prompt_tokens=20_000, completion_tokens=8_000)
        assert gate.tokens_used == 43_000


class TestSessionHardCap:
    def test_session_hard_cap_returns_abort_reason(self):
        """Accumulating past session_hard_cap returns a non-None reason."""
        gate = _make_gate(session_hard_cap=10_000, session_warn_threshold=8_000, per_turn_hard_cap=50_000)
        # First turn: under cap
        assert gate.record_turn(prompt_tokens=5_000, completion_tokens=2_000) is None
        # Second turn: crosses session cap
        reason = gate.record_turn(prompt_tokens=3_000, completion_tokens=1_000)
        assert reason is not None
        assert "session_hard_cap" in reason
        assert "10,000" in reason  # cap mentioned in message

    def test_abort_reason_is_string(self):
        gate = _make_gate(session_hard_cap=100, session_warn_threshold=80, per_turn_hard_cap=50_000)
        gate.record_turn(prompt_tokens=60, completion_tokens=0)
        reason = gate.record_turn(prompt_tokens=60, completion_tokens=0)
        assert isinstance(reason, str)
        assert len(reason) > 10


class TestPerTurnHardCap:
    def test_per_turn_hard_cap_returns_abort_reason(self):
        """A single huge turn that exceeds per_turn_hard_cap → abort reason."""
        gate = _make_gate(per_turn_hard_cap=50_000)
        reason = gate.record_turn(prompt_tokens=48_000, completion_tokens=5_000)
        assert reason is not None
        assert "per_turn_hard_cap" in reason

    def test_per_turn_cap_checked_before_accumulation(self):
        """Per-turn cap fires before session cap — both limits can be in play."""
        gate = _make_gate(session_hard_cap=200_000, per_turn_hard_cap=1_000)
        reason = gate.record_turn(prompt_tokens=999, completion_tokens=2)
        assert reason is not None
        assert "per_turn_hard_cap" in reason

    def test_under_per_turn_cap_passes(self):
        gate = _make_gate(per_turn_hard_cap=50_000)
        assert gate.record_turn(prompt_tokens=25_000, completion_tokens=24_999) is None

    def test_exactly_at_per_turn_cap_passes(self):
        """Exactly at cap (not over) is fine."""
        gate = _make_gate(per_turn_hard_cap=50_000)
        assert gate.record_turn(prompt_tokens=40_000, completion_tokens=10_000) is None

    def test_one_over_per_turn_cap_aborts(self):
        gate = _make_gate(per_turn_hard_cap=50_000)
        reason = gate.record_turn(prompt_tokens=40_000, completion_tokens=10_001)
        assert reason is not None


class TestSoftWarning:
    def test_soft_warn_logs_but_returns_none(self, caplog):
        """Crossing warn threshold logs a warning but does NOT abort."""
        gate = _make_gate(
            session_hard_cap=200_000,
            session_warn_threshold=10_000,
            per_turn_hard_cap=50_000,
        )
        with caplog.at_level(logging.WARNING, logger="agent.cost_gate"):
            reason = gate.record_turn(prompt_tokens=8_000, completion_tokens=4_000)

        assert reason is None  # not an abort
        assert any("WARNING" in r.levelname or "warning" in r.message.lower() for r in caplog.records)

    def test_soft_warn_emitted_only_once(self, caplog):
        """Warning fires once when threshold is first crossed, not on every turn after."""
        gate = _make_gate(
            session_hard_cap=200_000,
            session_warn_threshold=10_000,
            per_turn_hard_cap=50_000,
        )
        with caplog.at_level(logging.WARNING, logger="agent.cost_gate"):
            gate.record_turn(prompt_tokens=8_000, completion_tokens=4_000)  # crosses warn
            gate.record_turn(prompt_tokens=1_000, completion_tokens=500)    # stays above warn
        warn_records = [r for r in caplog.records if r.levelname == "WARNING"]
        assert len(warn_records) == 1

    def test_no_warning_below_threshold(self, caplog):
        gate = _make_gate(session_warn_threshold=100_000)
        with caplog.at_level(logging.WARNING, logger="agent.cost_gate"):
            gate.record_turn(prompt_tokens=5_000, completion_tokens=3_000)
        warn_records = [r for r in caplog.records if r.levelname == "WARNING"]
        assert len(warn_records) == 0


class TestResetSession:
    def test_reset_session_clears_counter(self):
        gate = _make_gate()
        gate.record_turn(prompt_tokens=50_000, completion_tokens=20_000)
        assert gate.tokens_used == 70_000

        gate.reset_session()
        assert gate.tokens_used == 0

    def test_reset_allows_warn_to_fire_again(self, caplog):
        gate = _make_gate(session_warn_threshold=10_000)
        with caplog.at_level(logging.WARNING, logger="agent.cost_gate"):
            gate.record_turn(prompt_tokens=8_000, completion_tokens=4_000)  # warn fires
        gate.reset_session()

        with caplog.at_level(logging.WARNING, logger="agent.cost_gate"):
            gate.record_turn(prompt_tokens=8_000, completion_tokens=4_000)  # warn fires again
        warn_records = [r for r in caplog.records if r.levelname == "WARNING"]
        assert len(warn_records) == 2

    def test_reset_allows_session_cap_to_be_re_breached(self):
        gate = _make_gate(session_hard_cap=10_000, per_turn_hard_cap=50_000)
        gate.record_turn(prompt_tokens=6_000, completion_tokens=0)
        reason = gate.record_turn(prompt_tokens=6_000, completion_tokens=0)
        assert reason is not None  # cap reached

        gate.reset_session()
        assert gate.record_turn(prompt_tokens=6_000, completion_tokens=0) is None  # back under


class TestGetState:
    def test_state_includes_tokens_used(self):
        gate = _make_gate(session_hard_cap=200_000)
        gate.record_turn(prompt_tokens=12_000, completion_tokens=3_000)
        state = gate.get_state()
        assert "tokens_used_session" in state
        assert state["tokens_used_session"] == 15_000

    def test_state_includes_budget(self):
        gate = _make_gate(session_hard_cap=99_000)
        state = gate.get_state()
        assert state["tokens_budget_session"] == 99_000

    def test_state_includes_last_warning_at(self):
        gate = _make_gate(session_warn_threshold=10_000, session_hard_cap=200_000, per_turn_hard_cap=50_000)
        state_before = gate.get_state()
        assert state_before["last_warning_at"] is None

        gate.record_turn(prompt_tokens=8_000, completion_tokens=4_000)  # crosses warn
        state_after = gate.get_state()
        assert state_after["last_warning_at"] == 12_000  # total at warn time

    def test_state_keys_match_contract(self):
        """Keys must match state.json CONTRACT schema."""
        gate = _make_gate()
        state = gate.get_state()
        for key in ("tokens_used_session", "tokens_budget_session", "last_warning_at"):
            assert key in state, f"missing CONTRACT key: {key}"


class TestConfigOverrides:
    def test_config_overrides_defaults(self, tmp_path):
        """Loading from a custom config file overrides the dataclass defaults."""
        from agent.control.cost_gate import CostBudget

        config = tmp_path / "budget.json"
        config.write_text(json.dumps({
            "session_hard_cap": 50_000,
            "session_warn_threshold": 40_000,
            "per_turn_hard_cap": 10_000,
        }))
        budget = CostBudget.from_config(config)
        assert budget.session_hard_cap == 50_000
        assert budget.session_warn_threshold == 40_000
        assert budget.per_turn_hard_cap == 10_000

    def test_missing_config_uses_defaults(self, tmp_path):
        """If config file doesn't exist, fall back to dataclass defaults."""
        from agent.control.cost_gate import CostBudget
        budget = CostBudget.from_config(tmp_path / "nonexistent.json")
        assert budget.session_hard_cap == 200_000
        assert budget.session_warn_threshold == 150_000
        assert budget.per_turn_hard_cap == 50_000

    def test_corrupt_config_uses_defaults(self, tmp_path):
        """Corrupt JSON in config → fall back to defaults, no exception raised."""
        from agent.control.cost_gate import CostBudget
        bad_config = tmp_path / "bad.json"
        bad_config.write_text("{not valid json")
        budget = CostBudget.from_config(bad_config)
        assert budget.session_hard_cap == 200_000

    def test_partial_config_merges_with_defaults(self, tmp_path):
        """Config with only some keys: specified keys override, others stay default."""
        from agent.control.cost_gate import CostBudget
        config = tmp_path / "partial.json"
        config.write_text(json.dumps({"session_hard_cap": 75_000}))
        budget = CostBudget.from_config(config)
        assert budget.session_hard_cap == 75_000
        assert budget.session_warn_threshold == 150_000  # default
        assert budget.per_turn_hard_cap == 50_000        # default


# ─────────────────────────────────────────────────────────────────────────────
# check_cost_usage() integration (runtime.py)
# ─────────────────────────────────────────────────────────────────────────────

class TestRuntimeCheckCostUsage:
    """Test the check_cost_usage() shim in agent/runtime.py."""

    def test_check_cost_usage_returns_none_under_budget(self, monkeypatch):
        """Normal usage → check_cost_usage returns None."""
        from agent.control.cost_gate import CostGate, CostBudget
        import agent.runtime as rt

        fresh_gate = CostGate(budget=CostBudget(
            session_hard_cap=200_000,
            session_warn_threshold=150_000,
            per_turn_hard_cap=50_000,
        ))
        monkeypatch.setattr(rt, "_cost_gate", fresh_gate)
        result = rt.check_cost_usage({"prompt_tokens": 1_000, "completion_tokens": 500})
        assert result is None

    def test_check_cost_usage_aborts_over_cap(self, monkeypatch):
        """Over session cap → check_cost_usage returns abort reason."""
        from agent.control.cost_gate import CostGate, CostBudget
        import agent.runtime as rt

        small_gate = CostGate(budget=CostBudget(
            session_hard_cap=100,
            session_warn_threshold=80,
            per_turn_hard_cap=50_000,
        ))
        monkeypatch.setattr(rt, "_cost_gate", small_gate)
        rt.check_cost_usage({"prompt_tokens": 60, "completion_tokens": 0})  # under
        reason = rt.check_cost_usage({"prompt_tokens": 60, "completion_tokens": 0})  # over
        assert reason is not None
        assert "session_hard_cap" in reason

    def test_check_cost_usage_handles_openrouter_key_names(self, monkeypatch):
        """OpenRouter uses input_tokens/output_tokens instead of prompt_/completion_."""
        from agent.control.cost_gate import CostGate, CostBudget
        import agent.runtime as rt

        gate = CostGate(budget=CostBudget())
        monkeypatch.setattr(rt, "_cost_gate", gate)
        result = rt.check_cost_usage({"input_tokens": 2_000, "output_tokens": 800})
        assert result is None
        assert gate.tokens_used == 2_800

    def test_check_cost_usage_with_no_gate(self, monkeypatch):
        """If _cost_gate is None (import failed), check_cost_usage returns None gracefully."""
        import agent.runtime as rt
        monkeypatch.setattr(rt, "_cost_gate", None)
        assert rt.check_cost_usage({"prompt_tokens": 999_999, "completion_tokens": 0}) is None

    def test_get_cost_gate_state_no_gate(self, monkeypatch):
        import agent.runtime as rt
        monkeypatch.setattr(rt, "_cost_gate", None)
        assert rt.get_cost_gate_state() == {}
