"""Tests for the agent control router (web/api/routers/agent.py).

Contract: agent/control/CONTRACT.md
Control is cross-process via the shared state file — we test by writing to /
reading from a temp state file, not by calling AgentControl in-process.

Auth pattern mirrors test_web_news_router.py: lifespan sets auth_token=None
(dev mode) or a known token for auth-required tests.
"""

from __future__ import annotations

import json
from contextlib import asynccontextmanager
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from web.api.routers import agent as agent_mod


# ── App factory ────────────────────────────────────────────────────────────────


def _make_app(token: str | None = None) -> FastAPI:
    """Minimal FastAPI app with the agent router mounted.

    token=None  → dev mode (no auth check)
    token="tok" → auth required
    """

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.auth_token = token
        yield

    app = FastAPI(lifespan=lifespan)
    app.include_router(agent_mod.router, prefix="/agent")
    return app


# ── Fixtures ───────────────────────────────────────────────────────────────────


@pytest.fixture()
def state_path(tmp_path: Path) -> Path:
    """Return a temporary state file path, patched into the router module."""
    return tmp_path / "agent" / "state.json"


@pytest.fixture()
def client_no_auth(state_path: Path):
    """TestClient with auth disabled and state file redirected to tmp_path."""
    app = _make_app(token=None)
    with patch.object(agent_mod, "_STATE_PATH", state_path):
        with TestClient(app, raise_server_exceptions=True) as client:
            yield client


@pytest.fixture()
def client_with_token(state_path: Path):
    """TestClient with a known auth token and state file in tmp_path."""
    app = _make_app(token="test-secret")
    with patch.object(agent_mod, "_STATE_PATH", state_path):
        with TestClient(app, raise_server_exceptions=True) as client:
            yield client


# ── GET /agent/state ───────────────────────────────────────────────────────────


class TestGetState:
    def test_default_when_file_missing(self, client_no_auth):
        resp = client_no_auth.get("/agent/state")
        assert resp.status_code == 200
        body = resp.json()
        assert body["is_running"] is False
        assert body["session_id"] is None

    def test_returns_file_contents(self, client_no_auth, state_path: Path):
        state_path.parent.mkdir(parents=True, exist_ok=True)
        state_path.write_text(
            json.dumps(
                {
                    "is_running": True,
                    "session_id": "abc-123",
                    "current_turn": 5,
                    "abort_flag": False,
                    "steering_queue": [],
                    "follow_up_queue": [],
                }
            )
        )
        resp = client_no_auth.get("/agent/state")
        assert resp.status_code == 200
        body = resp.json()
        assert body["is_running"] is True
        assert body["session_id"] == "abc-123"
        assert body["current_turn"] == 5

    def test_no_auth_required(self, client_with_token):
        """GET /state must NOT require Bearer auth — read-only."""
        # No Authorization header — must still succeed
        resp = client_with_token.get("/agent/state")
        assert resp.status_code == 200


# ── POST /agent/abort ──────────────────────────────────────────────────────────


class TestAbort:
    def test_writes_abort_flag(self, client_no_auth, state_path: Path):
        resp = client_no_auth.post(
            "/agent/abort", json={"reason": "operator stop"}
        )
        assert resp.status_code == 200
        assert resp.json()["ok"] is True
        assert resp.json()["abort_flag"] is True

        written = json.loads(state_path.read_text())
        assert written["abort_flag"] is True
        assert written["abort_reason"] == "operator stop"

    def test_preserves_existing_state(self, client_no_auth, state_path: Path):
        state_path.parent.mkdir(parents=True, exist_ok=True)
        state_path.write_text(
            json.dumps(
                {
                    "is_running": True,
                    "session_id": "sess-1",
                    "current_turn": 3,
                    "abort_flag": False,
                    "steering_queue": [{"text": "go faster", "queued_at": "2026-01-01T00:00:00+00:00"}],
                    "follow_up_queue": [],
                }
            )
        )
        client_no_auth.post("/agent/abort", json={"reason": "test"})
        written = json.loads(state_path.read_text())
        assert written["abort_flag"] is True
        # Existing fields preserved
        assert written["session_id"] == "sess-1"
        assert len(written["steering_queue"]) == 1

    def test_requires_auth_when_token_set(self, client_with_token):
        resp = client_with_token.post("/agent/abort", json={"reason": "stop"})
        assert resp.status_code == 401

    def test_auth_accepted_with_bearer(self, client_with_token):
        resp = client_with_token.post(
            "/agent/abort",
            json={"reason": "stop"},
            headers={"Authorization": "Bearer test-secret"},
        )
        assert resp.status_code == 200
        assert resp.json()["ok"] is True


# ── POST /agent/steer ──────────────────────────────────────────────────────────


class TestSteer:
    def test_appends_to_steering_queue(self, client_no_auth, state_path: Path):
        resp = client_no_auth.post(
            "/agent/steer", json={"message": "focus on BRENTOIL"}
        )
        assert resp.status_code == 200
        assert resp.json()["ok"] is True
        assert resp.json()["queue_depth"] == 1

        written = json.loads(state_path.read_text())
        assert len(written["steering_queue"]) == 1
        assert written["steering_queue"][0]["text"] == "focus on BRENTOIL"
        assert "queued_at" in written["steering_queue"][0]

    def test_appends_to_existing_queue(self, client_no_auth, state_path: Path):
        state_path.parent.mkdir(parents=True, exist_ok=True)
        state_path.write_text(
            json.dumps({"steering_queue": [{"text": "first", "queued_at": "t"}]})
        )
        client_no_auth.post("/agent/steer", json={"message": "second"})
        written = json.loads(state_path.read_text())
        assert len(written["steering_queue"]) == 2
        assert written["steering_queue"][1]["text"] == "second"

    def test_requires_auth_when_token_set(self, client_with_token):
        resp = client_with_token.post(
            "/agent/steer", json={"message": "hello"}
        )
        assert resp.status_code == 401


# ── POST /agent/follow-up ──────────────────────────────────────────────────────


class TestFollowUp:
    def test_appends_to_follow_up_queue(self, client_no_auth, state_path: Path):
        resp = client_no_auth.post(
            "/agent/follow-up", json={"message": "run the sweep"}
        )
        assert resp.status_code == 200
        assert resp.json()["ok"] is True
        assert resp.json()["queue_depth"] == 1

        written = json.loads(state_path.read_text())
        assert len(written["follow_up_queue"]) == 1
        assert written["follow_up_queue"][0]["text"] == "run the sweep"

    def test_appends_to_existing_queue(self, client_no_auth, state_path: Path):
        state_path.parent.mkdir(parents=True, exist_ok=True)
        state_path.write_text(
            json.dumps({"follow_up_queue": [{"text": "existing", "queued_at": "t"}]})
        )
        client_no_auth.post("/agent/follow-up", json={"message": "new one"})
        written = json.loads(state_path.read_text())
        assert len(written["follow_up_queue"]) == 2

    def test_requires_auth_when_token_set(self, client_with_token):
        resp = client_with_token.post(
            "/agent/follow-up", json={"message": "hello"}
        )
        assert resp.status_code == 401


# ── POST /agent/clear-queues ───────────────────────────────────────────────────


class TestClearQueues:
    def test_empties_both_queues(self, client_no_auth, state_path: Path):
        state_path.parent.mkdir(parents=True, exist_ok=True)
        state_path.write_text(
            json.dumps(
                {
                    "steering_queue": [{"text": "a", "queued_at": "t"}],
                    "follow_up_queue": [{"text": "b", "queued_at": "t"}, {"text": "c", "queued_at": "t"}],
                    "is_running": True,
                }
            )
        )
        resp = client_no_auth.post("/agent/clear-queues")
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert body["steering_queue"] == []
        assert body["follow_up_queue"] == []

        written = json.loads(state_path.read_text())
        assert written["steering_queue"] == []
        assert written["follow_up_queue"] == []
        # Other state preserved
        assert written["is_running"] is True

    def test_idempotent_when_already_empty(self, client_no_auth, state_path: Path):
        resp = client_no_auth.post("/agent/clear-queues")
        assert resp.status_code == 200
        body = resp.json()
        assert body["steering_queue"] == []
        assert body["follow_up_queue"] == []

    def test_requires_auth_when_token_set(self, client_with_token):
        resp = client_with_token.post("/agent/clear-queues")
        assert resp.status_code == 401
