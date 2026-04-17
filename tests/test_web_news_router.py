"""Tests for the news detail endpoint (web/api/routers/news.py)."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest


# ── Helpers ────────────────────────────────────────────────────────────────────


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    with open(path, "w") as f:
        for row in rows:
            f.write(json.dumps(row) + "\n")


# ── Unit tests for helper functions ───────────────────────────────────────────


class TestCoinMatches:
    def test_exact_match(self):
        from web.api.routers.news import _coin_matches
        assert _coin_matches("BTC", "BTC")

    def test_xyz_prefix_stripped(self):
        from web.api.routers.news import _coin_matches
        assert _coin_matches("xyz:BRENTOIL", "xyz:BRENTOIL")

    def test_cross_prefix(self):
        from web.api.routers.news import _coin_matches
        assert _coin_matches("xyz:GOLD", "GOLD")

    def test_no_match(self):
        from web.api.routers.news import _coin_matches
        assert not _coin_matches("BTC", "BRENTOIL")


class TestLinkedTheses:
    def test_matches_instrument(self, tmp_path):
        thesis = {
            "market": "xyz:BRENTOIL",
            "direction": "long",
            "conviction": 0.7,
            "thesis_summary": "Oil bull thesis",
            "invalidation_conditions": [],
        }
        (tmp_path / "xyz_brentoil_state.json").write_text(json.dumps(thesis))

        from web.api.routers import news as news_mod

        with patch.object(news_mod, "_THESIS_DIR", tmp_path):
            result = news_mod._linked_theses(["xyz:BRENTOIL", "CL"])

        assert len(result) == 1
        assert result[0]["market"] == "xyz:BRENTOIL"
        assert result[0]["conviction"] == 0.7

    def test_no_match_returns_empty(self, tmp_path):
        thesis = {"market": "BTC", "direction": "long", "conviction": 0.5, "thesis_summary": "", "invalidation_conditions": []}
        (tmp_path / "btc_state.json").write_text(json.dumps(thesis))

        from web.api.routers import news as news_mod

        with patch.object(news_mod, "_THESIS_DIR", tmp_path):
            result = news_mod._linked_theses(["xyz:BRENTOIL"])

        assert result == []

    def test_empty_instruments(self, tmp_path):
        from web.api.routers import news as news_mod

        with patch.object(news_mod, "_THESIS_DIR", tmp_path):
            result = news_mod._linked_theses([])

        assert result == []


class TestAuditRows:
    def test_missing_audit_file(self, tmp_path):
        from web.api.routers import news as news_mod

        with patch.object(news_mod, "_THESIS_DIR", tmp_path):
            result = news_mod._audit_rows_for("abc123")

        assert result == []

    def test_matching_rows_returned(self, tmp_path):
        rows = [
            {"id": "abc123", "delta": -0.1},
            {"catalyst_id": "abc123", "delta": -0.2},
            {"id": "other", "delta": 0.5},
        ]
        _write_jsonl(tmp_path / "audit.jsonl", rows)

        from web.api.routers import news as news_mod

        with patch.object(news_mod, "_THESIS_DIR", tmp_path):
            result = news_mod._audit_rows_for("abc123")

        assert len(result) == 2


class TestBuildCatalystIndex:
    def test_indexes_by_id(self, tmp_path):
        catalysts = [
            {"id": "cat1", "headline_id": "h1", "instruments": ["BTC"], "severity": 3},
            {"id": "cat2", "headline_id": "h2", "instruments": ["GOLD"], "severity": 5},
        ]
        catalyst_path = tmp_path / "news" / "catalysts.jsonl"
        catalyst_path.parent.mkdir(parents=True)
        _write_jsonl(catalyst_path, catalysts)

        from web.api.routers import news as news_mod

        with (
            patch.object(news_mod, "DATA_DIR", tmp_path),
            patch.object(news_mod, "_HEADLINES_PATH", tmp_path / "news" / "headlines.jsonl"),
        ):
            index = news_mod._build_catalyst_index()

        assert "cat1" in index
        assert index["cat1"]["headline_id"] == "h1"
        assert "cat2" in index

    def test_skips_rows_without_id(self, tmp_path):
        catalysts = [{"headline_id": "h1"}, {"id": "cat2", "severity": 1}]
        catalyst_path = tmp_path / "news" / "catalysts.jsonl"
        catalyst_path.parent.mkdir(parents=True)
        _write_jsonl(catalyst_path, catalysts)

        from web.api.routers import news as news_mod

        with patch.object(news_mod, "DATA_DIR", tmp_path):
            index = news_mod._build_catalyst_index()

        assert list(index.keys()) == ["cat2"]


class TestBuildHeadlineIndex:
    def test_indexes_by_id(self, tmp_path):
        headlines = [
            {"id": "h1", "title": "Oil strike", "body_excerpt": "Full text here", "source": "reuters"},
            {"id": "h2", "title": "Gold moves", "body_excerpt": "Details...", "source": "bloomberg"},
        ]
        hl_path = tmp_path / "headlines.jsonl"
        _write_jsonl(hl_path, headlines)

        from web.api.routers import news as news_mod

        with patch.object(news_mod, "_HEADLINES_PATH", hl_path):
            index = news_mod._build_headline_index()

        assert index["h1"]["title"] == "Oil strike"
        assert "h2" in index

    def test_missing_file_returns_empty(self, tmp_path):
        from web.api.routers import news as news_mod

        with patch.object(news_mod, "_HEADLINES_PATH", tmp_path / "nonexistent.jsonl"):
            index = news_mod._build_headline_index()

        assert index == {}


class TestGetCatalystDetailLogic:
    """Integration-style tests against the full endpoint logic via FastAPI test client."""

    def _make_app(self):
        """Create a minimal FastAPI app with no auth token so auth is skipped."""
        from fastapi import FastAPI
        from contextlib import asynccontextmanager
        from web.api.routers.news import router

        @asynccontextmanager
        async def lifespan(app):
            app.state.auth_token = None  # dev mode — skip auth
            yield

        app = FastAPI(lifespan=lifespan)
        app.include_router(router, prefix="/news")
        return app

    def test_404_for_unknown_id(self, tmp_path):
        from fastapi.testclient import TestClient
        from web.api.routers import news as news_mod

        app = self._make_app()
        with (
            patch.object(news_mod, "_build_catalyst_index", return_value={}),
            patch.object(news_mod, "_build_headline_index", return_value={}),
            patch.object(news_mod, "_linked_theses", return_value=[]),
            patch.object(news_mod, "_audit_rows_for", return_value=[]),
        ):
            client = TestClient(app, raise_server_exceptions=True)
            resp = client.get("/news/catalyst/doesnotexist")

        assert resp.status_code == 404

    def test_returns_catalyst_and_headline(self, tmp_path):
        from fastapi.testclient import TestClient
        from web.api.routers import news as news_mod

        catalyst_row = {"id": "c1", "headline_id": "h1", "instruments": ["xyz:BRENTOIL"], "severity": 4, "rationale": "big deal"}
        headline_row = {"id": "h1", "title": "Strike hits pipeline", "body_excerpt": "Full article...", "source": "reuters", "url": "https://example.com/1"}

        app = self._make_app()
        with (
            patch.object(news_mod, "_build_catalyst_index", return_value={"c1": catalyst_row}),
            patch.object(news_mod, "_build_headline_index", return_value={"h1": headline_row}),
            patch.object(news_mod, "_linked_theses", return_value=[]),
            patch.object(news_mod, "_audit_rows_for", return_value=[]),
        ):
            client = TestClient(app, raise_server_exceptions=True)
            resp = client.get("/news/catalyst/c1")

        assert resp.status_code == 200
        body = resp.json()
        assert body["catalyst"]["id"] == "c1"
        assert body["headline"]["title"] == "Strike hits pipeline"
        assert body["headline_missing"] is False
        assert body["linked_theses"] == []
        assert body["audit_rows"] == []

    def test_headline_missing_flag(self, tmp_path):
        from fastapi.testclient import TestClient
        from web.api.routers import news as news_mod

        catalyst_row = {"id": "c2", "headline_id": "h_gone", "instruments": ["BTC"], "severity": 2}

        app = self._make_app()
        with (
            patch.object(news_mod, "_build_catalyst_index", return_value={"c2": catalyst_row}),
            patch.object(news_mod, "_build_headline_index", return_value={}),
            patch.object(news_mod, "_linked_theses", return_value=[]),
            patch.object(news_mod, "_audit_rows_for", return_value=[]),
        ):
            client = TestClient(app, raise_server_exceptions=True)
            resp = client.get("/news/catalyst/c2")

        assert resp.status_code == 200
        body = resp.json()
        assert body["headline"] is None
        assert body["headline_missing"] is True

    def test_linked_theses_populated(self, tmp_path):
        from fastapi.testclient import TestClient
        from web.api.routers import news as news_mod

        catalyst_row = {"id": "c3", "headline_id": "h3", "instruments": ["xyz:GOLD"], "severity": 3}
        linked = [{"market": "xyz:GOLD", "direction": "long", "conviction": 0.6, "thesis_summary": "Gold bull", "invalidation_conditions": []}]

        app = self._make_app()
        with (
            patch.object(news_mod, "_build_catalyst_index", return_value={"c3": catalyst_row}),
            patch.object(news_mod, "_build_headline_index", return_value={}),
            patch.object(news_mod, "_linked_theses", return_value=linked),
            patch.object(news_mod, "_audit_rows_for", return_value=[]),
        ):
            client = TestClient(app, raise_server_exceptions=True)
            resp = client.get("/news/catalyst/c3")

        assert resp.status_code == 200
        body = resp.json()
        assert len(body["linked_theses"]) == 1
        assert body["linked_theses"][0]["market"] == "xyz:GOLD"
        assert body["linked_theses"][0]["conviction"] == pytest.approx(0.6)
