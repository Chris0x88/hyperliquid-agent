"""Tests for durable pending action store in agent_tools.

Verifies that pending approvals survive simulated bot restarts by
persisting to disk and rehydrating on load.
"""
import json
import time
from pathlib import Path
from unittest.mock import patch

import pytest


@pytest.fixture(autouse=True)
def _isolate_pending(tmp_path):
    """Redirect pending actions file to tmp_path for test isolation."""
    pending_file = tmp_path / "pending_actions.json"
    import agent.tools as at

    orig_file = at._PENDING_FILE
    orig_actions = at._pending_actions.copy()
    at._PENDING_FILE = pending_file
    at._pending_actions.clear()
    yield pending_file
    at._PENDING_FILE = orig_file
    at._pending_actions = orig_actions


def test_store_persists_to_disk(_isolate_pending):
    """Stored pending action should be written to disk."""
    from agent.tools import store_pending

    pending_file = _isolate_pending
    action_id = store_pending("place_trade", {"coin": "BTC", "side": "buy", "size": 1}, "12345")
    assert pending_file.exists()
    data = json.loads(pending_file.read_text())
    assert action_id in data
    assert data[action_id]["tool"] == "place_trade"


def test_pop_removes_from_disk(_isolate_pending):
    """Popping an action should remove it from the persistent file."""
    from agent.tools import store_pending, pop_pending

    pending_file = _isolate_pending
    action_id = store_pending("set_sl", {"coin": "BTC", "trigger_price": 50000}, "12345")
    action = pop_pending(action_id)
    assert action is not None
    assert action["tool"] == "set_sl"
    data = json.loads(pending_file.read_text())
    assert action_id not in data


def test_survives_restart(_isolate_pending):
    """Simulated restart: clear in-memory dict, reload from disk."""
    import agent.tools as at

    pending_file = _isolate_pending
    action_id = at.store_pending("place_trade", {"coin": "GOLD", "side": "buy", "size": 0.5}, "12345")

    # Simulate restart: clear memory, reload from file
    at._pending_actions.clear()
    at._load_pending()

    action = at.pop_pending(action_id)
    assert action is not None
    assert action["arguments"]["coin"] == "GOLD"


def test_expired_not_reloaded(_isolate_pending):
    """Expired actions should not be rehydrated on restart."""
    import agent.tools as at

    pending_file = _isolate_pending
    # Write an already-expired entry directly
    expired = {
        "old123": {
            "tool": "place_trade",
            "arguments": {"coin": "BTC"},
            "chat_id": "12345",
            "ts": time.time() - 600,  # 10 min ago, well past 5 min TTL
        }
    }
    pending_file.write_text(json.dumps(expired))
    at._load_pending()
    assert at.pop_pending("old123") is None


def test_cleanup_persists(_isolate_pending):
    """cleanup_expired_pending should persist removal to disk."""
    import agent.tools as at

    pending_file = _isolate_pending
    # Inject an expired entry into memory + disk
    at._pending_actions["exp1"] = {
        "tool": "set_tp",
        "arguments": {},
        "chat_id": "12345",
        "ts": time.time() - 600,
    }
    at._persist_pending()
    removed = at.cleanup_expired_pending()
    assert removed == 1
    data = json.loads(pending_file.read_text())
    assert "exp1" not in data
