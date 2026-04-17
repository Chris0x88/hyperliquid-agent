"""Tests for iterator description enrichment in the daemon router.

Verifies that:
  - The /iterators endpoint includes all new description fields
  - Hand-curated descriptions (ITERATOR_DESCRIPTIONS) take priority
  - Auto-extraction falls back gracefully when no curated entry exists
  - _get_iterator_meta never throws for any known iterator name
"""

from __future__ import annotations

import json
import sys
from contextlib import asynccontextmanager
from pathlib import Path
from unittest.mock import patch

import pytest

# Ensure agent-cli is on sys.path
_root = Path(__file__).resolve().parent.parent
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))


# ── Helpers ────────────────────────────────────────────────────────────────────


def _make_app():
    """Minimal FastAPI app with daemon router, no auth."""
    from fastapi import FastAPI
    from web.api.routers.daemon import router

    @asynccontextmanager
    async def lifespan(app):
        app.state.auth_token = None  # dev mode — skip auth
        yield

    app = FastAPI(lifespan=lifespan)
    app.include_router(router, prefix="/daemon")
    return app


# ── Unit tests for _get_iterator_meta ─────────────────────────────────────────


class TestGetIteratorMeta:
    def test_curated_description_returned_for_known_name(self):
        from web.api.routers.daemon import _get_iterator_meta

        meta = _get_iterator_meta("telegram")
        assert meta["description"] is not None
        assert "Telegram" in meta["description"]
        assert meta["kill_switch_impact"] is not None
        assert "ALL alerts go silent" in meta["kill_switch_impact"]
        assert isinstance(meta["inputs"], list)
        assert isinstance(meta["outputs"], list)

    def test_curated_category_is_set(self):
        from web.api.routers.daemon import _get_iterator_meta

        assert _get_iterator_meta("telegram")["category"] == "Operations"
        assert _get_iterator_meta("risk")["category"] == "Safety"
        assert _get_iterator_meta("thesis_engine")["category"] == "Intelligence"
        assert _get_iterator_meta("journal")["category"] == "Self-improvement"
        assert _get_iterator_meta("oil_botpattern")["category"] == "Trading"

    def test_tier_set_populated(self):
        from web.api.routers.daemon import _get_iterator_meta

        # telegram is in every tier
        meta = _get_iterator_meta("telegram")
        assert len(meta["tier_set"]) >= 1

    def test_config_path_format(self):
        from web.api.routers.daemon import _get_iterator_meta

        meta = _get_iterator_meta("news_ingest")
        assert meta["config_path"] == "data/config/news_ingest.json"

    def test_source_file_format(self):
        from web.api.routers.daemon import _get_iterator_meta

        meta = _get_iterator_meta("news_ingest")
        # news_ingest.py exists in the iterators dir
        assert meta["source_file"] == "daemon/iterators/news_ingest.py"

    def test_unknown_iterator_does_not_raise(self):
        """A name that doesn't exist should return nulls, not raise."""
        from web.api.routers.daemon import _get_iterator_meta

        meta = _get_iterator_meta("totally_unknown_iterator_xyz")
        assert meta["description"] is None
        assert meta["purpose"] is None
        assert meta["kill_switch_impact"] is None
        assert isinstance(meta["inputs"], list)
        assert isinstance(meta["outputs"], list)

    def test_all_known_iterators_do_not_raise(self):
        """Smoke test: every iterator in tiers.py must produce a valid meta dict."""
        from daemon.tiers import TIER_ITERATORS
        from web.api.routers.daemon import _get_iterator_meta

        all_names: set[str] = set()
        for tier_list in TIER_ITERATORS.values():
            all_names.update(tier_list)

        for name in all_names:
            meta = _get_iterator_meta(name)
            assert isinstance(meta, dict), f"meta for {name} must be a dict"
            assert "description" in meta, f"meta for {name} missing 'description'"
            assert "category" in meta, f"meta for {name} missing 'category'"
            assert isinstance(meta["inputs"], list), f"inputs for {name} must be list"
            assert isinstance(meta["outputs"], list), f"outputs for {name} must be list"


# ── Docstring extraction ───────────────────────────────────────────────────────


class TestExtractDocstring:
    def test_known_iterator_returns_docstring(self):
        from web.api.routers.daemon import _extract_docstring

        first_line, full_doc = _extract_docstring("news_ingest")
        assert first_line is not None
        assert full_doc is not None
        assert len(full_doc) > 20

    def test_missing_iterator_returns_none(self):
        from web.api.routers.daemon import _extract_docstring

        first_line, full_doc = _extract_docstring("does_not_exist_xyz")
        assert first_line is None
        assert full_doc is None

    def test_curated_iterator_still_has_docstring(self):
        """Curated iterators should also have docstrings — verifies source files exist."""
        from web.api.routers.daemon import _extract_docstring

        # These are curated AND have source files
        for name in ("account_collector", "journal", "risk"):
            first, full = _extract_docstring(name)
            assert first is not None, f"{name} should have a docstring"


# ── Endpoint integration tests ─────────────────────────────────────────────────


class TestIteratorsEndpoint:
    def test_endpoint_returns_description_fields(self, tmp_path):
        """GET /daemon/iterators must include all new description keys."""
        from fastapi.testclient import TestClient
        from web.api import routers as _rmod
        import web.api.routers.daemon as daemon_mod

        with patch.object(daemon_mod, "DATA_DIR", tmp_path):
            client = TestClient(_make_app(), raise_server_exceptions=True)
            resp = client.get("/daemon/iterators")

        assert resp.status_code == 200
        body = resp.json()
        assert "iterators" in body
        assert len(body["iterators"]) > 0

        first = body["iterators"][0]
        for field in ("description", "purpose", "kill_switch_impact", "inputs", "outputs", "category", "tier_set", "config_path", "source_file"):
            assert field in first, f"Missing field '{field}' in iterator response"

    def test_enabled_state_read_from_config(self, tmp_path):
        """enabled=false in a config file is reflected in the response."""
        import web.api.routers.daemon as daemon_mod
        from fastapi.testclient import TestClient

        cfg_dir = tmp_path / "config"
        cfg_dir.mkdir(parents=True)
        (cfg_dir / "news_ingest.json").write_text(json.dumps({"enabled": False}))

        with patch.object(daemon_mod, "DATA_DIR", tmp_path):
            client = TestClient(_make_app(), raise_server_exceptions=True)
            resp = client.get("/daemon/iterators")

        body = resp.json()
        news = next((it for it in body["iterators"] if it["name"] == "news_ingest"), None)
        assert news is not None
        assert news["enabled"] is False

    def test_inputs_and_outputs_are_lists(self, tmp_path):
        """inputs and outputs must always be lists, never None."""
        import web.api.routers.daemon as daemon_mod
        from fastapi.testclient import TestClient

        with patch.object(daemon_mod, "DATA_DIR", tmp_path):
            client = TestClient(_make_app(), raise_server_exceptions=True)
            resp = client.get("/daemon/iterators")

        for it in resp.json()["iterators"]:
            assert isinstance(it["inputs"], list), f"inputs not list for {it['name']}"
            assert isinstance(it["outputs"], list), f"outputs not list for {it['name']}"


# ── iterator_descriptions module ──────────────────────────────────────────────


class TestIteratorDescriptionsModule:
    def test_all_curated_have_required_fields(self):
        from web.api.iterator_descriptions import ITERATOR_DESCRIPTIONS

        required = ("description", "purpose", "kill_switch_impact", "inputs", "outputs", "category")
        for name, entry in ITERATOR_DESCRIPTIONS.items():
            for field in required:
                assert field in entry, f"ITERATOR_DESCRIPTIONS[{name!r}] missing field '{field}'"

    def test_curated_descriptions_are_non_empty(self):
        from web.api.iterator_descriptions import ITERATOR_DESCRIPTIONS

        for name, entry in ITERATOR_DESCRIPTIONS.items():
            assert entry["description"], f"Empty description for {name!r}"
            assert entry["purpose"], f"Empty purpose for {name!r}"
            assert entry["kill_switch_impact"], f"Empty kill_switch_impact for {name!r}"

    def test_category_values_are_valid(self):
        from web.api.iterator_descriptions import ITERATOR_DESCRIPTIONS

        valid = {"Trading", "Safety", "Intelligence", "Self-improvement", "Operations"}
        for name, entry in ITERATOR_DESCRIPTIONS.items():
            assert entry["category"] in valid, f"Invalid category '{entry['category']}' for {name!r}"
