"""Tests for agent/control/agent_control.py and the ControlledAgentLoop.

Contract: agent/control/CONTRACT.md
"""
from __future__ import annotations

import json
import os
import tempfile
import threading
import time
from pathlib import Path
from typing import List
from unittest.mock import MagicMock

import pytest


# ─────────────────────────────────────────────────────────────────────────────
# Helpers / fixtures
# ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture
def tmp_state_file(tmp_path):
    """Return a Path inside a tmp dir for the state file."""
    return tmp_path / "state.json"


@pytest.fixture
def ctrl(tmp_state_file):
    """Fresh AgentControl backed by a temp file."""
    from agent.control.agent_control import AgentControl
    return AgentControl(state_path=tmp_state_file)


def _parse_state(path: Path) -> dict:
    """Read and parse the state file — asserts it is always valid JSON."""
    with open(path, encoding="utf-8") as f:
        return json.load(f)


# ─────────────────────────────────────────────────────────────────────────────
# 1. State file always valid JSON
# ─────────────────────────────────────────────────────────────────────────────

class TestStateFileAlwaysValidJson:
    def test_initial_write_is_valid_json(self, ctrl, tmp_state_file):
        state = _parse_state(tmp_state_file)
        assert isinstance(state, dict)

    def test_after_abort_still_valid(self, ctrl, tmp_state_file):
        ctrl.abort("test")
        state = _parse_state(tmp_state_file)
        assert state["abort_flag"] is True

    def test_after_steer_still_valid(self, ctrl, tmp_state_file):
        ctrl.steer("hello world")
        state = _parse_state(tmp_state_file)
        assert isinstance(state["steering_queue"], list)
        assert state["steering_queue"][0]["text"] == "hello world"

    def test_after_follow_up_still_valid(self, ctrl, tmp_state_file):
        ctrl.follow_up("do more")
        state = _parse_state(tmp_state_file)
        assert isinstance(state["follow_up_queue"], list)

    def test_after_set_state_still_valid(self, ctrl, tmp_state_file):
        ctrl.set_state(is_running=True, current_turn=3)
        state = _parse_state(tmp_state_file)
        assert state["is_running"] is True
        assert state["current_turn"] == 3


# ─────────────────────────────────────────────────────────────────────────────
# 2. Abort flag
# ─────────────────────────────────────────────────────────────────────────────

class TestAbortFlag:
    def test_not_aborted_initially(self, ctrl):
        assert ctrl.is_aborted() is False

    def test_abort_raises_flag(self, ctrl):
        ctrl.abort("user_requested")
        assert ctrl.is_aborted() is True

    def test_abort_reason_stored(self, ctrl, tmp_state_file):
        ctrl.abort("some reason")
        state = _parse_state(tmp_state_file)
        assert state["abort_reason"] == "some reason"
        assert state["abort_flag"] is True

    def test_abort_never_auto_recovers(self, ctrl):
        ctrl.abort()
        # Calling steer or other methods must not reset the abort flag
        ctrl.steer("hi")
        ctrl.follow_up("foo")
        assert ctrl.is_aborted() is True


# ─────────────────────────────────────────────────────────────────────────────
# 3. Queue bounds — 11th item evicts oldest
# ─────────────────────────────────────────────────────────────────────────────

class TestQueueBounds:
    def test_steering_queue_max_10_items(self, ctrl, tmp_state_file):
        for i in range(12):
            ctrl.steer(f"msg {i}")
        state = _parse_state(tmp_state_file)
        assert len(state["steering_queue"]) == 10

    def test_steering_queue_evicts_oldest(self, ctrl, tmp_state_file):
        for i in range(11):
            ctrl.steer(f"msg {i}")
        state = _parse_state(tmp_state_file)
        texts = [e["text"] for e in state["steering_queue"]]
        # msg 0 should have been evicted; msg 1 should be the oldest now
        assert "msg 0" not in texts
        assert "msg 1" in texts
        assert "msg 10" in texts

    def test_follow_up_queue_max_10_items(self, ctrl, tmp_state_file):
        for i in range(15):
            ctrl.follow_up(f"task {i}")
        state = _parse_state(tmp_state_file)
        assert len(state["follow_up_queue"]) == 10

    def test_follow_up_queue_evicts_oldest(self, ctrl, tmp_state_file):
        for i in range(11):
            ctrl.follow_up(f"task {i}")
        state = _parse_state(tmp_state_file)
        texts = [e["text"] for e in state["follow_up_queue"]]
        assert "task 0" not in texts
        assert "task 10" in texts


# ─────────────────────────────────────────────────────────────────────────────
# 4. Clear queue methods
# ─────────────────────────────────────────────────────────────────────────────

class TestClearQueues:
    def test_clear_steering_queue(self, ctrl, tmp_state_file):
        ctrl.steer("a")
        ctrl.steer("b")
        ctrl.clear_steering_queue()
        state = _parse_state(tmp_state_file)
        assert state["steering_queue"] == []

    def test_clear_follow_up_queue(self, ctrl, tmp_state_file):
        ctrl.follow_up("x")
        ctrl.clear_follow_up_queue()
        state = _parse_state(tmp_state_file)
        assert state["follow_up_queue"] == []

    def test_clear_all_queues(self, ctrl, tmp_state_file):
        ctrl.steer("s")
        ctrl.follow_up("f")
        ctrl.clear_all_queues()
        state = _parse_state(tmp_state_file)
        assert state["steering_queue"] == []
        assert state["follow_up_queue"] == []


# ─────────────────────────────────────────────────────────────────────────────
# 5. drain_steering_queue / pop_follow_up
# ─────────────────────────────────────────────────────────────────────────────

class TestDrainHelpers:
    def test_drain_returns_all_and_clears(self, ctrl, tmp_state_file):
        ctrl.steer("first")
        ctrl.steer("second")
        msgs = ctrl.drain_steering_queue()
        assert [m["text"] for m in msgs] == ["first", "second"]
        state = _parse_state(tmp_state_file)
        assert state["steering_queue"] == []

    def test_drain_empty_returns_empty_list(self, ctrl):
        assert ctrl.drain_steering_queue() == []

    def test_pop_follow_up_fifo(self, ctrl):
        ctrl.follow_up("first")
        ctrl.follow_up("second")
        assert ctrl.pop_follow_up()["text"] == "first"
        assert ctrl.pop_follow_up()["text"] == "second"
        assert ctrl.pop_follow_up() is None

    def test_pop_follow_up_empty(self, ctrl):
        assert ctrl.pop_follow_up() is None


# ─────────────────────────────────────────────────────────────────────────────
# 6. get_state / set_state schema
# ─────────────────────────────────────────────────────────────────────────────

class TestGetSetState:
    def test_get_state_has_required_keys(self, ctrl):
        s = ctrl.get_state()
        required = {
            "is_running", "session_id", "started_at", "current_turn",
            "current_tool", "abort_flag", "abort_reason", "steering_queue",
            "follow_up_queue", "turn_timeout_s", "tokens_used_session",
            "tokens_budget_session", "last_event",
        }
        for k in required:
            assert k in s, f"Missing key: {k}"

    def test_set_state_updates_fields(self, ctrl, tmp_state_file):
        ctrl.set_state(is_running=True, current_turn=7, tokens_used_session=999)
        state = _parse_state(tmp_state_file)
        assert state["is_running"] is True
        assert state["current_turn"] == 7
        assert state["tokens_used_session"] == 999

    def test_set_state_is_running_sets_started_at(self, ctrl):
        assert ctrl.get_state()["started_at"] is None
        ctrl.set_state(is_running=True)
        assert ctrl.get_state()["started_at"] is not None

    def test_set_state_abort_flag(self, ctrl, tmp_state_file):
        ctrl.set_state(abort_flag=True, abort_reason="manual")
        state = _parse_state(tmp_state_file)
        assert state["abort_flag"] is True
        assert state["abort_reason"] == "manual"


# ─────────────────────────────────────────────────────────────────────────────
# 7. ControlledAgentLoop — abort halts within one tool boundary
# ─────────────────────────────────────────────────────────────────────────────

class TestControlledAgentLoop:
    """Integration tests for ControlledAgentLoop using mock LLM/tool callables."""

    def _make_stream_result(self, text="OK", tool_calls=None):
        from agent.runtime import StreamResult
        r = StreamResult()
        r.text = text
        r.tool_calls = tool_calls or []
        r.stop_reason = "end_turn" if not tool_calls else "tool_use"
        return r

    def _loop(self, ctrl):
        from agent.runtime import ControlledAgentLoop
        return ControlledAgentLoop(control=ctrl)

    def test_simple_run_no_tools(self, ctrl):
        """Single LLM call with no tools — returns the text."""
        sr = self._make_stream_result("Hello!")
        call_llm = MagicMock(return_value=sr)
        tool_fn = MagicMock(return_value="unused")

        loop = self._loop(ctrl)
        result = loop.run(
            prompt="hi",
            call_llm_fn=call_llm,
            execute_tool_fn=tool_fn,
            messages=[],
        )
        assert result["text"] == "Hello!"
        assert result["aborted"] is False
        assert result["turns"] == 1
        tool_fn.assert_not_called()

    def test_abort_before_first_llm_call(self, ctrl):
        """abort() before run → loop exits immediately."""
        ctrl.abort("pre_abort")
        call_llm = MagicMock()
        loop = self._loop(ctrl)
        result = loop.run(
            prompt="hi",
            call_llm_fn=call_llm,
            execute_tool_fn=MagicMock(return_value=""),
            messages=[],
        )
        assert result["aborted"] is True
        call_llm.assert_not_called()

    def test_abort_halts_at_tool_boundary(self, ctrl):
        """Abort raised during tool execution halts BEFORE the next tool."""
        tool_call_count = [0]

        # LLM returns two tool calls
        tc1 = {"id": "t1", "type": "function", "function": {"name": "tool_a", "arguments": "{}"}}
        tc2 = {"id": "t2", "type": "function", "function": {"name": "tool_b", "arguments": "{}"}}
        sr_with_tools = self._make_stream_result("doing stuff", [tc1, tc2])
        call_llm = MagicMock(return_value=sr_with_tools)

        def tool_fn(name, args):
            tool_call_count[0] += 1
            if name == "tool_a":
                ctrl.abort("mid_tool_abort")
            return f"result_{name}"

        loop = self._loop(ctrl)
        result = loop.run(
            prompt="do both tools",
            call_llm_fn=call_llm,
            execute_tool_fn=tool_fn,
            messages=[],
        )
        # tool_a ran, abort was set, tool_b should NOT have run
        assert result["aborted"] is True
        assert tool_call_count[0] == 1  # only tool_a executed

    def test_steer_injected_before_next_llm_turn(self, ctrl):
        """Steering messages appear in messages before the 2nd LLM call."""
        injected_messages = []

        call_count = [0]

        def call_llm(messages):
            call_count[0] += 1
            if call_count[0] == 1:
                # First call: return one tool to trigger a second turn
                tc = {"id": "t1", "type": "function",
                       "function": {"name": "read_file", "arguments": '{"path": "x"}'}}
                sr = self._make_stream_result("reading", [tc])
            else:
                # Capture messages for assertion
                injected_messages.extend(messages)
                sr = self._make_stream_result("done")
            return sr

        def tool_fn(name, args):
            # Inject a steer message while the tool runs (simulates Telegram /steer)
            ctrl.steer("STEERED_MESSAGE")
            return "file contents"

        loop = self._loop(ctrl)
        loop.run(
            prompt="start",
            call_llm_fn=call_llm,
            execute_tool_fn=tool_fn,
            messages=[],
        )
        # The steer message should appear in the messages seen by the 2nd LLM call
        contents = [m.get("content", "") for m in injected_messages]
        assert "STEERED_MESSAGE" in contents

    def test_follow_up_runs_after_natural_end(self, ctrl):
        """Follow-up queue is drained when the loop would otherwise end."""
        call_count = [0]
        prompts_seen = []

        def call_llm(messages):
            call_count[0] += 1
            # Capture the last user message
            user_msgs = [m for m in messages if m.get("role") == "user"]
            if user_msgs:
                prompts_seen.append(user_msgs[-1]["content"])
            return self._make_stream_result("ok")

        ctrl.follow_up("FOLLOW_UP_TASK")

        loop = self._loop(ctrl)
        result = loop.run(
            prompt="initial",
            call_llm_fn=call_llm,
            execute_tool_fn=MagicMock(return_value=""),
            messages=[],
        )
        assert result["aborted"] is False
        assert call_count[0] == 2  # initial + follow-up
        assert "FOLLOW_UP_TASK" in prompts_seen

    def test_turn_timeout_aborts_cleanly(self, ctrl):
        """When call_llm_fn exceeds turn_timeout_s, abort fires with 'turn_timeout'."""
        import threading

        def slow_llm(messages):
            # Sleep longer than the timeout
            time.sleep(5)
            return self._make_stream_result("never reached")

        loop = self._loop(ctrl)
        result = loop.run(
            prompt="hi",
            call_llm_fn=slow_llm,
            execute_tool_fn=MagicMock(return_value=""),
            messages=[],
            turn_timeout_s=1,  # 1-second timeout
        )
        assert result["aborted"] is True
        state = ctrl.get_state()
        assert state["abort_flag"] is True
        assert "turn_timeout" in state["abort_reason"]

    def test_state_file_valid_after_every_transition(self, ctrl, tmp_state_file):
        """The state file must be parseable JSON at every point in the run."""
        parse_errors = []
        original_flush = ctrl._flush

        def flush_and_check():
            original_flush()
            try:
                _parse_state(tmp_state_file)
            except Exception as e:
                parse_errors.append(str(e))

        ctrl._flush = flush_and_check

        # Run a simple 1-tool loop
        tc = {"id": "t1", "type": "function",
               "function": {"name": "read_file", "arguments": '{"path": "x"}'}}
        call_count = [0]

        def call_llm(messages):
            call_count[0] += 1
            if call_count[0] == 1:
                return self._make_stream_result("reading", [tc])
            return self._make_stream_result("done")

        loop = self._loop(ctrl)
        loop.run(
            prompt="go",
            call_llm_fn=call_llm,
            execute_tool_fn=MagicMock(return_value="content"),
            messages=[],
        )

        assert parse_errors == [], f"State file had JSON errors: {parse_errors}"

    def test_multiple_follow_ups_all_drain(self, ctrl):
        """Multiple follow-ups in queue all get executed sequentially."""
        call_count = [0]

        def call_llm(messages):
            call_count[0] += 1
            return self._make_stream_result("ok")

        ctrl.follow_up("task 2")
        ctrl.follow_up("task 3")

        loop = self._loop(ctrl)
        loop.run(
            prompt="task 1",
            call_llm_fn=call_llm,
            execute_tool_fn=MagicMock(return_value=""),
            messages=[],
        )
        assert call_count[0] == 3  # initial + 2 follow-ups
        assert ctrl.pop_follow_up() is None  # queue empty

    def test_abort_prevents_follow_up_from_running(self, ctrl):
        """If aborted during run, follow-up is NOT started."""
        call_count = [0]

        def call_llm(messages):
            call_count[0] += 1
            ctrl.abort("mid_run")
            return self._make_stream_result("done")

        ctrl.follow_up("should not run")

        loop = self._loop(ctrl)
        result = loop.run(
            prompt="go",
            call_llm_fn=call_llm,
            execute_tool_fn=MagicMock(return_value=""),
            messages=[],
        )
        assert result["aborted"] is True
        assert call_count[0] == 1  # follow-up never triggered


# ─────────────────────────────────────────────────────────────────────────────
# 8. Thread safety — concurrent steer/abort from different threads
# ─────────────────────────────────────────────────────────────────────────────

class TestThreadSafety:
    def test_concurrent_steers_do_not_corrupt_queue(self, ctrl, tmp_state_file):
        """100 concurrent steer calls must not raise or corrupt the file."""
        errors = []

        def _steer(i):
            try:
                ctrl.steer(f"msg {i}")
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=_steer, args=(i,)) for i in range(100)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert errors == []
        state = _parse_state(tmp_state_file)
        # Queue is bounded at 10
        assert len(state["steering_queue"]) <= 10

    def test_abort_from_background_thread(self, ctrl, tmp_state_file):
        """abort() from a background thread is visible to is_aborted() on main."""
        def _abort():
            time.sleep(0.05)
            ctrl.abort("background_thread")

        t = threading.Thread(target=_abort)
        t.start()
        t.join()

        assert ctrl.is_aborted() is True
        state = _parse_state(tmp_state_file)
        assert state["abort_reason"] == "background_thread"


# ─────────────────────────────────────────────────────────────────────────────
# 9. GateDecision dataclass
# ─────────────────────────────────────────────────────────────────────────────

class TestGateDecision:
    def test_defaults(self):
        from agent.control import GateDecision
        gd = GateDecision(allow=True)
        assert gd.allow is True
        assert gd.block_reason is None
        assert gd.requires_approval is False
        assert gd.transformed_args is None

    def test_blocked(self):
        from agent.control import GateDecision
        gd = GateDecision(allow=False, block_reason="too risky")
        assert gd.allow is False
        assert gd.block_reason == "too risky"
