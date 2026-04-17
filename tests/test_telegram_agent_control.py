"""Tests for telegram/commands/agent_control.py.

All five commands are deterministic Python — no AI calls.
The AgentControl class is mocked via unittest.mock because its implementation
is being built in parallel (only the CONTRACT exists).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# ── Path setup ─────────────────────────────────────────────────────────────
PROJECT_ROOT = str(Path(__file__).resolve().parent.parent)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

# Import the module under test once; patches target its attributes directly.
import telegram.commands.agent_control as _mod

TOKEN = "test-token"
CHAT = "chat-99"


def _make_running_state(**overrides) -> dict:
    base = {
        "is_running": True,
        "session_id": "abcd-1234-efgh",
        "started_at": "2026-04-17T00:00:00Z",
        "current_turn": 3,
        "current_tool": {
            "name": "edit_file",
            "args_summary": "bot.py",
            "started_at": "2026-04-17T00:01:00Z",
        },
        "abort_flag": False,
        "abort_reason": None,
        "steering_queue": [],
        "follow_up_queue": [],
        "turn_timeout_s": 60,
        "tokens_used_session": 12345,
        "tokens_budget_session": 200000,
        "last_event": {},
    }
    base.update(overrides)
    return base


# ── /stop ───────────────────────────────────────────────────────────────────

def test_stop_when_no_run(tmp_path):
    """Graceful response when no state file exists."""
    sent = []
    with patch.object(_mod, "_read_state", return_value=None), \
         patch("telegram.api.tg_send", side_effect=lambda t, c, m: sent.append(m)):
        _mod.cmd_stop(TOKEN, CHAT, "")

    assert len(sent) == 1
    assert "No active agent run" in sent[0]


def test_stop_when_running():
    """Calls abort() with the right reason and returns the expected response."""
    ctrl = MagicMock()
    sent = []
    with patch.object(_mod, "_read_state", return_value=_make_running_state()), \
         patch.object(_mod, "_get_control", return_value=ctrl), \
         patch("telegram.api.tg_send", side_effect=lambda t, c, m: sent.append(m)):
        _mod.cmd_stop(TOKEN, CHAT, "")

    ctrl.abort.assert_called_once_with("user_requested via /stop")
    assert len(sent) == 1
    msg = sent[0]
    assert "Stopping" in msg
    assert "current tool will finish" in msg


def test_stop_when_idle():
    """No abort called if agent is present but not running."""
    sent = []
    idle = _make_running_state(is_running=False)
    with patch.object(_mod, "_read_state", return_value=idle), \
         patch("telegram.api.tg_send", side_effect=lambda t, c, m: sent.append(m)):
        _mod.cmd_stop(TOKEN, CHAT, "")

    assert "No active agent run" in sent[0]


# ── /steer ───────────────────────────────────────────────────────────────────

def test_steer_with_message():
    """Calls steer(msg) once and includes the message preview in the response."""
    ctrl = MagicMock()
    sent = []
    with patch.object(_mod, "_read_state", return_value=_make_running_state()), \
         patch.object(_mod, "_get_control", return_value=ctrl), \
         patch("telegram.api.tg_send", side_effect=lambda t, c, m: sent.append(m)):
        _mod.cmd_steer(TOKEN, CHAT, "focus on BRENTOIL funding")

    ctrl.steer.assert_called_once_with("focus on BRENTOIL funding")
    assert len(sent) == 1
    assert "focus on BRENTOIL funding" in sent[0]
    assert "queued" in sent[0].lower()


def test_steer_no_message():
    """Returns a usage hint when no message is provided."""
    sent = []
    with patch.object(_mod, "_read_state", return_value=_make_running_state()), \
         patch("telegram.api.tg_send", side_effect=lambda t, c, m: sent.append(m)):
        _mod.cmd_steer(TOKEN, CHAT, "")

    assert len(sent) == 1
    assert "Usage" in sent[0] or "usage" in sent[0]


def test_steer_when_no_run():
    """Returns 'No active agent run' when state file is absent."""
    sent = []
    with patch.object(_mod, "_read_state", return_value=None), \
         patch("telegram.api.tg_send", side_effect=lambda t, c, m: sent.append(m)):
        _mod.cmd_steer(TOKEN, CHAT, "do something")

    assert "No active agent run" in sent[0]


# ── /cancel ───────────────────────────────────────────────────────────────────

def test_cancel_drops_pending_approvals():
    """Clears pending approvals and reports the count dropped."""
    ctrl = MagicMock()
    sent = []
    fake_pending = {"id1": {}, "id2": {}, "id3": {}}

    with patch.object(_mod, "_read_state", return_value=_make_running_state()), \
         patch.object(_mod, "_get_control", return_value=ctrl), \
         patch("agent.tools._pending_actions", fake_pending), \
         patch("telegram.api.tg_send", side_effect=lambda t, c, m: sent.append(m)):
        _mod.cmd_cancel(TOKEN, CHAT, "")

    ctrl.abort.assert_called_once()
    assert len(sent) == 1
    msg = sent[0]
    assert "3" in msg
    assert "Cancelled" in msg or "abort" in msg.lower()


def test_cancel_when_no_run_still_clears_approvals():
    """Even with no running agent, pending approvals should be cleared."""
    sent = []
    fake_pending = {"x": {}}

    with patch.object(_mod, "_read_state", return_value=None), \
         patch("agent.tools._pending_actions", fake_pending), \
         patch("telegram.api.tg_send", side_effect=lambda t, c, m: sent.append(m)):
        _mod.cmd_cancel(TOKEN, CHAT, "")

    assert len(sent) == 1
    msg = sent[0]
    assert "1" in msg or "dropped" in msg


# ── /follow ───────────────────────────────────────────────────────────────────

def test_follow_with_message():
    """Calls follow_up(msg) and includes the message preview in the response."""
    ctrl = MagicMock()
    sent = []
    with patch.object(_mod, "_get_control", return_value=ctrl), \
         patch("telegram.api.tg_send", side_effect=lambda t, c, m: sent.append(m)):
        _mod.cmd_follow(TOKEN, CHAT, "check GOLD thesis after this")

    ctrl.follow_up.assert_called_once_with("check GOLD thesis after this")
    assert len(sent) == 1
    assert "check GOLD thesis after this" in sent[0]
    assert "queued" in sent[0].lower()


def test_follow_no_message():
    """Returns a usage hint when no message is provided."""
    sent = []
    with patch("telegram.api.tg_send", side_effect=lambda t, c, m: sent.append(m)):
        _mod.cmd_follow(TOKEN, CHAT, "")

    assert len(sent) == 1
    assert "Usage" in sent[0] or "usage" in sent[0]


# ── /agentstate ───────────────────────────────────────────────────────────────

def test_agentstate_no_state_file():
    """Returns a graceful empty-state response when the state file is absent."""
    sent = []
    with patch.object(_mod, "_read_state", return_value=None), \
         patch("telegram.api.tg_send", side_effect=lambda t, c, m: sent.append(m)):
        _mod.cmd_agentstate(TOKEN, CHAT, "")

    assert len(sent) == 1
    msg = sent[0]
    assert "No state file" in msg or "not running" in msg.lower()


def test_agentstate_pretty_prints():
    """Returns a human-readable formatted status from the state file."""
    state = _make_running_state(
        abort_flag=False,
        steering_queue=[{"text": "steer me", "queued_at": "2026-04-17T00:00:00Z"}],
        follow_up_queue=[],
        tokens_used_session=50000,
        tokens_budget_session=200000,
    )
    sent = []
    with patch.object(_mod, "_read_state", return_value=state), \
         patch("telegram.api.tg_send", side_effect=lambda t, c, m: sent.append(m)):
        _mod.cmd_agentstate(TOKEN, CHAT, "")

    assert len(sent) == 1
    msg = sent[0]
    assert "Running" in msg
    assert "yes" in msg
    assert "Turn" in msg
    assert "edit_file" in msg
    assert "Steering" in msg
    assert "50,000" in msg or "50000" in msg


def test_agentstate_shows_abort_flag():
    """Shows abort flag as SET with reason when it is raised."""
    state = _make_running_state(
        abort_flag=True,
        abort_reason="user_requested via /stop",
    )
    sent = []
    with patch.object(_mod, "_read_state", return_value=state), \
         patch("telegram.api.tg_send", side_effect=lambda t, c, m: sent.append(m)):
        _mod.cmd_agentstate(TOKEN, CHAT, "")

    msg = sent[0]
    assert "SET" in msg
    assert "user_requested" in msg
