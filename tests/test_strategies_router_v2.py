"""Tests for the expanded strategies router (v2 endpoints).

Covers:
- GET /strategies/registry — live/parked/library grouping
- GET /strategies/oil-botpattern/detail — sub-systems + sub6 layers
- GET /strategies/oil-botpattern/activity — merge decisions + shadow trades
- GET /strategies/lab/status — kanban + archetypes
- GET /strategies/oil-botpattern/shadow-summary — balance + positions
- POST /strategies/lab/backtest — approved markets, stub archetypes
"""

from __future__ import annotations

import json
from contextlib import asynccontextmanager
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


# ── App factory ────────────────────────────────────────────────────────────────

def _make_app() -> TestClient:
    from web.api.routers.strategies import router

    @asynccontextmanager
    async def lifespan(app):
        app.state.auth_token = None  # skip auth in tests
        yield

    app = FastAPI(lifespan=lifespan)
    app.include_router(router, prefix="/strategies")
    return TestClient(app, raise_server_exceptions=True)


# ── Helpers ────────────────────────────────────────────────────────────────────

def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data))


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        for row in rows:
            f.write(json.dumps(row) + "\n")


# ── Registry tests ─────────────────────────────────────────────────────────────

class TestRegistryEndpoint:
    def test_returns_three_groups(self, tmp_path):
        from web.api.routers import strategies as mod

        _write_json(tmp_path / "config" / "oil_botpattern.json", {
            "enabled": True, "decisions_only": True, "instruments": ["BRENTOIL"]
        })
        _write_json(tmp_path / "daemon" / "roster.json", [
            {"name": "power_law_btc", "strategy_path": "strategies.power_law_btc:PowerLawBTCStrategy",
             "instrument": "BTC-PERP", "paused": False, "params": {"simulate": True}}
        ])
        _write_json(tmp_path / "strategy" / "oil_botpattern_shadow_balance.json", {
            "seed_balance_usd": 100000,
            "current_balance_usd": 99900,
            "realised_pnl_usd": -100.0,
            "pnl_pct": -0.001,
            "win_rate": 0.0,
            "closed_trades": 2,
            "wins": 0,
            "losses": 2,
            "last_updated_at": None,
        })

        client = _make_app()
        with (
            patch.object(mod, "_CONFIG_DIR", tmp_path / "config"),
            patch.object(mod, "_STRATEGY_DIR", tmp_path / "strategy"),
            patch.object(mod, "DATA_DIR", tmp_path),
        ):
            resp = client.get("/strategies/registry")

        assert resp.status_code == 200
        body = resp.json()
        assert "live" in body
        assert "parked" in body
        assert "library" in body
        assert "counts" in body
        assert body["counts"]["library"] > 0

    def test_oil_botpattern_in_live_when_shadow(self, tmp_path):
        from web.api.routers import strategies as mod

        _write_json(tmp_path / "config" / "oil_botpattern.json", {
            "enabled": True, "decisions_only": True, "instruments": ["BRENTOIL"]
        })
        _write_json(tmp_path / "daemon" / "roster.json", [])
        _write_json(tmp_path / "strategy" / "oil_botpattern_shadow_balance.json", {})

        client = _make_app()
        with (
            patch.object(mod, "_CONFIG_DIR", tmp_path / "config"),
            patch.object(mod, "_STRATEGY_DIR", tmp_path / "strategy"),
            patch.object(mod, "DATA_DIR", tmp_path),
        ):
            resp = client.get("/strategies/registry")

        body = resp.json()
        live_ids = [e["id"] for e in body["live"]]
        assert "oil_botpattern" in live_ids

    def test_status_is_shadow_when_decisions_only(self, tmp_path):
        from web.api.routers import strategies as mod

        _write_json(tmp_path / "config" / "oil_botpattern.json", {
            "enabled": True, "decisions_only": True, "instruments": []
        })
        _write_json(tmp_path / "daemon" / "roster.json", [])
        _write_json(tmp_path / "strategy" / "oil_botpattern_shadow_balance.json", {})

        client = _make_app()
        with (
            patch.object(mod, "_CONFIG_DIR", tmp_path / "config"),
            patch.object(mod, "_STRATEGY_DIR", tmp_path / "strategy"),
            patch.object(mod, "DATA_DIR", tmp_path),
        ):
            resp = client.get("/strategies/registry")

        body = resp.json()
        obp = next(e for e in body["live"] if e["id"] == "oil_botpattern")
        assert obp["status"] == "SHADOW"


# ── Detail tests ───────────────────────────────────────────────────────────────

class TestDetailEndpoint:
    def test_returns_all_keys(self, tmp_path):
        from web.api.routers import strategies as mod

        for cfg_name in ["oil_botpattern", "news_ingest", "supply_ledger", "heatmap",
                         "bot_classifier", "self_tune"]:
            _write_json(tmp_path / "config" / f"{cfg_name}.json", {"enabled": True})
        for cfg_name in ["oil_botpattern_tune", "oil_botpattern_reflect",
                         "oil_botpattern_patternlib", "oil_botpattern_shadow"]:
            _write_json(tmp_path / "config" / f"{cfg_name}.json", {"enabled": False})

        _write_json(tmp_path / "strategy" / "oil_botpattern_state.json", {})
        _write_json(tmp_path / "strategy" / "oil_botpattern_shadow_balance.json", {
            "seed_balance_usd": 100000, "current_balance_usd": 100000,
        })
        _write_json(tmp_path / "strategy" / "oil_botpattern_shadow_positions.json", {"positions": []})
        _write_json(tmp_path / "strategy" / "oil_botpattern_patternlib_state.json", {
            "last_run_at": "2026-04-17T00:00:00+00:00",
            "last_candidate_id": 53,
        })

        client = _make_app()
        with (
            patch.object(mod, "_CONFIG_DIR", tmp_path / "config"),
            patch.object(mod, "_STRATEGY_DIR", tmp_path / "strategy"),
        ):
            resp = client.get("/strategies/oil-botpattern/detail")

        assert resp.status_code == 200
        body = resp.json()
        assert "config" in body
        assert "sub_systems" in body
        assert "sub6_layers" in body
        assert "shadow_balance" in body
        assert "recent_shadow_trades" in body
        assert len(body["sub_systems"]) == 6
        assert len(body["sub6_layers"]) == 4

    def test_sub6_layer_enabled_state(self, tmp_path):
        from web.api.routers import strategies as mod

        _write_json(tmp_path / "config" / "oil_botpattern.json", {"enabled": True})
        for cfg_name in ["news_ingest", "supply_ledger", "heatmap", "bot_classifier", "self_tune"]:
            _write_json(tmp_path / "config" / f"{cfg_name}.json", {"enabled": True})
        # L3 enabled, rest off
        _write_json(tmp_path / "config" / "oil_botpattern_patternlib.json", {"enabled": True})
        for cfg_name in ["oil_botpattern_tune", "oil_botpattern_reflect", "oil_botpattern_shadow"]:
            _write_json(tmp_path / "config" / f"{cfg_name}.json", {"enabled": False})
        for fname in ["state", "shadow_balance", "shadow_positions", "patternlib_state"]:
            _write_json(tmp_path / "strategy" / f"oil_botpattern_{fname}.json", {})

        client = _make_app()
        with (
            patch.object(mod, "_CONFIG_DIR", tmp_path / "config"),
            patch.object(mod, "_STRATEGY_DIR", tmp_path / "strategy"),
        ):
            resp = client.get("/strategies/oil-botpattern/detail")

        body = resp.json()
        layers_by_id = {l["id"]: l for l in body["sub6_layers"]}
        assert layers_by_id["L3"]["enabled"] is True
        assert layers_by_id["L1"]["enabled"] is False
        assert layers_by_id["L2"]["enabled"] is False
        assert layers_by_id["L4"]["enabled"] is False


# ── Activity tests ─────────────────────────────────────────────────────────────

class TestActivityEndpoint:
    def test_returns_merged_feed(self, tmp_path):
        from web.api.routers import strategies as mod

        _write_jsonl(tmp_path / "strategy" / "oil_botpattern_adaptive_log.jsonl", [
            {
                "logged_at": "2026-04-10T08:00:00+00:00",
                "position": {"instrument": "BRENTOIL"},
                "decision": {"action": "hold", "reason": "hypothesis intact"},
            }
        ])
        _write_jsonl(tmp_path / "strategy" / "oil_botpattern_shadow_trades.jsonl", [
            {
                "instrument": "BRENTOIL",
                "exit_ts": "2026-04-10T07:32:00+00:00",
                "exit_reason": "sl_hit",
                "realised_pnl_usd": -0.50,
                "roe_pct": -6.0,
                "edge": 0.65,
                "hold_hours": 0.44,
            }
        ])

        client = _make_app()
        with (
            patch.object(mod, "_adaptive_log",
                         __import__("web.api.readers.jsonl_reader", fromlist=["FileEventReader"])
                         .FileEventReader(tmp_path / "strategy" / "oil_botpattern_adaptive_log.jsonl")),
            patch.object(mod, "_shadow_trades_reader",
                         __import__("web.api.readers.jsonl_reader", fromlist=["FileEventReader"])
                         .FileEventReader(tmp_path / "strategy" / "oil_botpattern_shadow_trades.jsonl")),
        ):
            resp = client.get("/strategies/oil-botpattern/activity?limit=20")

        assert resp.status_code == 200
        body = resp.json()
        assert body["count"] == 2
        types = {item["type"] for item in body["activity"]}
        assert "decision" in types
        assert "shadow_trade" in types

    def test_empty_when_no_files(self, tmp_path):
        from web.api.routers import strategies as mod
        from web.api.readers.jsonl_reader import FileEventReader

        client = _make_app()
        with (
            patch.object(mod, "_adaptive_log",
                         FileEventReader(tmp_path / "no_adaptive.jsonl")),
            patch.object(mod, "_shadow_trades_reader",
                         FileEventReader(tmp_path / "no_shadow.jsonl")),
        ):
            resp = client.get("/strategies/oil-botpattern/activity")

        assert resp.status_code == 200
        assert resp.json()["count"] == 0


# ── Lab status tests ───────────────────────────────────────────────────────────

class TestLabStatusEndpoint:
    def test_returns_archetypes(self, tmp_path):
        from web.api.routers import strategies as mod

        _write_json(tmp_path / "config" / "lab.json", {"enabled": False})

        client = _make_app()
        with patch.object(mod, "_CONFIG_DIR", tmp_path / "config"), \
             patch.object(mod, "_LAB_DIR", tmp_path / "lab"):
            resp = client.get("/strategies/lab/status")

        assert resp.status_code == 200
        body = resp.json()
        assert "archetypes" in body
        assert "kanban" in body
        arch_ids = [a["id"] for a in body["archetypes"]]
        assert "momentum_breakout" in arch_ids
        assert "mean_reversion" in arch_ids

    def test_momentum_breakout_wired_true(self, tmp_path):
        from web.api.routers import strategies as mod

        _write_json(tmp_path / "config" / "lab.json", {"enabled": False})

        client = _make_app()
        with patch.object(mod, "_CONFIG_DIR", tmp_path / "config"), \
             patch.object(mod, "_LAB_DIR", tmp_path / "lab"):
            resp = client.get("/strategies/lab/status")

        body = resp.json()
        mb = next(a for a in body["archetypes"] if a["id"] == "momentum_breakout")
        assert mb["wired"] is True

        others = [a for a in body["archetypes"] if a["id"] != "momentum_breakout"]
        for a in others:
            assert a["wired"] is False

    def test_approved_markets_listed(self, tmp_path):
        from web.api.routers import strategies as mod

        _write_json(tmp_path / "config" / "lab.json", {"enabled": False})

        client = _make_app()
        with patch.object(mod, "_CONFIG_DIR", tmp_path / "config"), \
             patch.object(mod, "_LAB_DIR", tmp_path / "lab"):
            resp = client.get("/strategies/lab/status")

        body = resp.json()
        assert "BRENTOIL" in body["approved_markets"]
        assert "BTC" in body["approved_markets"]


# ── Backtest endpoint tests ────────────────────────────────────────────────────

class TestBacktestEndpoint:
    def test_unapproved_market_returns_400(self):
        client = _make_app()
        resp = client.post("/strategies/lab/backtest", json={
            "market": "DOGE",
            "archetype": "momentum_breakout",
        })
        assert resp.status_code == 400
        assert "approved list" in resp.json()["detail"]

    def test_unknown_archetype_returns_400(self):
        client = _make_app()
        resp = client.post("/strategies/lab/backtest", json={
            "market": "BTC",
            "archetype": "nonexistent_archetype",
        })
        assert resp.status_code == 400

    def test_stub_archetype_returns_not_implemented(self):
        """Stub archetypes surface NotImplementedError as status=not_implemented.

        mean_reversion is a real stub — calling run_backtest on it should
        raise NotImplementedError which the endpoint catches cleanly.
        """
        import engines.learning.lab_engine as lab_mod

        client = _make_app()
        orig = lab_mod.LabEngine

        class _FakeLab:
            _config = {"enabled": True}

            def __init__(self, *a, **kw):
                pass

            def create_experiment(self, market, strategy, params):
                from engines.learning.lab_engine import Experiment
                import time, uuid
                return Experiment(
                    id="exp-stub",
                    market=market,
                    strategy=strategy,
                    params=params or {},
                    created_at=time.time(),
                    updated_at=time.time(),
                )

            def run_backtest(self, exp_id):
                raise NotImplementedError("mean_reversion not yet wired")

            def get_experiment(self, exp_id):
                return None

            def _load_experiments(self):
                pass

        lab_mod.LabEngine = _FakeLab
        try:
            resp = client.post("/strategies/lab/backtest", json={
                "market": "BRENTOIL",
                "archetype": "mean_reversion",
            })
        finally:
            lab_mod.LabEngine = orig

        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "not_implemented"
        assert "error" in body

    def test_xyz_prefix_stripped_from_market(self):
        """xyz: prefix is stripped before approval check — xyz:BRENTOIL should be valid."""
        client = _make_app()
        # The endpoint strips xyz: before checking _APPROVED_MARKETS.
        # If it doesn't strip, we'd get a 400. We expect not-400 (it might 500 if
        # the real LabEngine can't run, but that's fine — just not "approved list" error).
        resp = client.post("/strategies/lab/backtest", json={
            "market": "xyz:BRENTOIL",
            "archetype": "mean_reversion",  # stub raises NotImplementedError (200)
        })
        # Should either succeed (200) or fail for a reason other than approved-list
        if resp.status_code == 400:
            assert "approved list" not in resp.json().get("detail", "")


# ── Shadow summary tests ───────────────────────────────────────────────────────

class TestShadowSummaryEndpoint:
    def test_returns_balance_and_positions(self, tmp_path):
        from web.api.routers import strategies as mod

        _write_json(tmp_path / "strategy" / "oil_botpattern_shadow_balance.json", {
            "seed_balance_usd": 100000,
            "current_balance_usd": 99000,
            "realised_pnl_usd": -1000,
            "pnl_pct": -0.01,
            "win_rate": 0.3,
            "closed_trades": 10,
            "wins": 3,
            "losses": 7,
            "last_updated_at": "2026-04-17T00:00:00+00:00",
        })
        _write_json(tmp_path / "strategy" / "oil_botpattern_shadow_positions.json", {
            "positions": [{"instrument": "BRENTOIL", "size": 1.0}]
        })
        _write_jsonl(tmp_path / "strategy" / "oil_botpattern_shadow_trades.jsonl", [
            {
                "instrument": "BRENTOIL",
                "side": "long",
                "entry_price": 90.0,
                "exit_price": 85.0,
                "realised_pnl_usd": -500.0,
                "roe_pct": -6.0,
                "exit_reason": "sl_hit",
                "edge": 0.65,
                "hold_hours": 1.5,
                "entry_ts": "2026-04-10T06:00:00+00:00",
                "exit_ts": "2026-04-10T07:32:00+00:00",
            }
        ])

        client = _make_app()
        with (
            patch.object(mod, "_STRATEGY_DIR", tmp_path / "strategy"),
            patch.object(mod, "_shadow_trades_reader",
                         __import__("web.api.readers.jsonl_reader", fromlist=["FileEventReader"])
                         .FileEventReader(tmp_path / "strategy" / "oil_botpattern_shadow_trades.jsonl")),
        ):
            resp = client.get("/strategies/oil-botpattern/shadow-summary")

        assert resp.status_code == 200
        body = resp.json()
        assert body["balance"]["closed_trades"] == 10
        assert len(body["positions"]) == 1
        assert len(body["recent_trades"]) == 1
        assert body["recent_trades"][0]["exit_reason"] == "sl_hit"
