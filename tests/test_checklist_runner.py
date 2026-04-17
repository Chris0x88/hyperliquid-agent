"""Tests for engines/checklist/runner.py and end-to-end /evening synthetic scenario."""
from __future__ import annotations

import json
import time
from pathlib import Path
from unittest.mock import patch

import pytest

from engines.checklist.runner import run_checklist
from engines.checklist.spec import ChecklistResult


# ── Shared synthetic context ──────────────────────────────────

SILVER_LONG_POS = {
    "coin": "xyz:SILVER",
    "size": 50.0,
    "entry": 75.0,
    "upnl": -300.0,
    "leverage": "25",    # violates 3x thesis → FAIL on leverage_vs_thesis
    "margin_used": 3000.0,
    "liq": 68.0,
    "account_role": "main",
}

SL_ORDER = {
    "coin": "xyz:SILVER",
    "tpsl": "sl",
    "orderType": "Stop Market",
    "reduceOnly": True,
    "triggerPx": "68.0",
}

TP_ORDER = {
    "coin": "xyz:SILVER",
    "tpsl": "tp",
    "orderType": "Take Profit Market",
    "reduceOnly": True,
    "triggerPx": "95.0",
}

SILVER_THESIS = {
    "market": "xyz:SILVER",
    "direction": "long",
    "conviction": 0.55,
    "recommended_leverage": 3.0,
    "weekend_leverage_cap": 2.0,
    "take_profit_price": 95.0,
}

SWEEP_RESULT_ELEVATED = {
    "score": 2,
    "flags": ["Zone at $70", "Funding adverse"],
    "reasoning": "Two sweep indicators — elevated risk",
    "position_side": "long",
    "phase3_gaps": [],
}


def _make_ctx(**overrides):
    ctx = {
        "positions": [SILVER_LONG_POS],
        "orders": [SL_ORDER, TP_ORDER],
        "total_equity": 10000.0,
        "thesis": SILVER_THESIS,
        "market_price": 72.0,
        "atr": 2.5,
        "funding_rate": 0.0006,  # 65.7% annualised (8h rate) → FAIL funding_cost
        "catalysts": [],
        "heatmap_zones": [],
        "cascades": [],
        "bot_patterns": [],
        "closed_since": [],
        "filled_orders": [],
        "sweep_result": None,
        "is_friday_brisbane": False,
    }
    ctx.update(overrides)
    return ctx


# ── run_checklist tests ───────────────────────────────────────

class TestRunChecklist:
    def test_returns_dict(self, tmp_path):
        with patch("engines.checklist.runner.STATE_DIR", tmp_path):
            ctx = _make_ctx()
            result = run_checklist("xyz:SILVER", "evening", ctx)
        assert isinstance(result, dict)
        assert result["market"] == "xyz:SILVER"
        assert result["mode"] == "evening"
        assert "items" in result
        assert "status" in result
        assert "score" in result

    def test_evening_mode_items_only(self, tmp_path):
        """Evening mode must not include morning-only items."""
        with patch("engines.checklist.runner.STATE_DIR", tmp_path):
            ctx = _make_ctx()
            result = run_checklist("xyz:SILVER", "evening", ctx)
        item_names = {i["name"] for i in result["items"]}
        morning_only = {"overnight_fills", "overnight_closed", "cascade_events",
                        "new_catalysts", "pending_actions", "asia_setup"}
        assert item_names.isdisjoint(morning_only), \
            f"Evening has morning items: {item_names & morning_only}"

    def test_morning_mode_items_only(self, tmp_path):
        """Morning mode must not include evening-only items."""
        with patch("engines.checklist.runner.STATE_DIR", tmp_path):
            ctx = _make_ctx()
            result = run_checklist("xyz:SILVER", "morning", ctx)
        item_names = {i["name"] for i in result["items"]}
        evening_only = {"sl_on_exchange", "tp_on_exchange", "leverage_vs_thesis",
                        "weekend_leverage", "news_catalyst_12h", "funding_cost"}
        assert item_names.isdisjoint(evening_only), \
            f"Morning has evening items: {item_names & evening_only}"

    def test_invalid_mode_raises(self, tmp_path):
        with patch("engines.checklist.runner.STATE_DIR", tmp_path):
            ctx = _make_ctx()
            with pytest.raises(ValueError, match="Invalid mode"):
                run_checklist("xyz:SILVER", "lunchtime", ctx)

    def test_status_aggregation_fail_wins(self, tmp_path):
        """If any item fails, overall status is 'fail'."""
        with patch("engines.checklist.runner.STATE_DIR", tmp_path):
            ctx = _make_ctx()
            result = run_checklist("xyz:SILVER", "evening", ctx)
        # 25x leverage vs 3x thesis = fail, funding 78% ann = fail
        assert result["status"] == "fail"

    def test_score_is_float_between_0_and_1(self, tmp_path):
        with patch("engines.checklist.runner.STATE_DIR", tmp_path):
            ctx = _make_ctx()
            result = run_checklist("xyz:SILVER", "evening", ctx)
        assert 0.0 <= result["score"] <= 1.0

    def test_persists_to_state_dir(self, tmp_path):
        with patch("engines.checklist.runner.STATE_DIR", tmp_path):
            ctx = _make_ctx()
            run_checklist("xyz:SILVER", "evening", ctx)
        # Check that at least one JSON file was written
        files = list(tmp_path.glob("silver_evening_*.json"))
        assert len(files) == 1

    def test_updates_latest_json(self, tmp_path):
        with patch("engines.checklist.runner.STATE_DIR", tmp_path):
            ctx = _make_ctx()
            run_checklist("xyz:SILVER", "evening", ctx)
        latest_file = tmp_path / "latest.json"
        assert latest_file.exists()
        latest = json.loads(latest_file.read_text())
        assert "silver_evening" in latest

    def test_sweep_risk_item_included(self, tmp_path):
        """Sweep risk evaluator wires into checklist."""
        with patch("engines.checklist.runner.STATE_DIR", tmp_path):
            ctx = _make_ctx(sweep_result=SWEEP_RESULT_ELEVATED)
            result = run_checklist("xyz:SILVER", "evening", ctx)
        item_names = {i["name"] for i in result["items"]}
        assert "sweep_risk" in item_names

    def test_sweep_risk_fail_when_elevated(self, tmp_path):
        """Score 2 sweep_result → sweep_risk item should fail."""
        with patch("engines.checklist.runner.STATE_DIR", tmp_path):
            ctx = _make_ctx(sweep_result=SWEEP_RESULT_ELEVATED)
            result = run_checklist("xyz:SILVER", "evening", ctx)
        sweep_items = [i for i in result["items"] if i["name"] == "sweep_risk"]
        assert sweep_items
        assert sweep_items[0]["status"] == "fail"


# ── End-to-end: /evening on synthetic Silver LONG 25x ────────

class TestEveningEndToEnd:
    """Simulate exactly what /evening sees with the current SILVER position:
    - LONG 25x (violates 3x thesis)
    - No weekend cap issue (not Friday)
    - Funding rate at 78% annualised (FAIL)
    - Sweep risk elevated (WARN)
    - SL and TP present (PASS)
    Expected: overall FAIL, specific FAILs on leverage + funding
    """

    def test_silver_25x_evening_lights_up_fails(self, tmp_path):
        ctx = _make_ctx(
            sweep_result={"score": 1, "flags": ["Zone at $70"], "reasoning": "building",
                          "position_side": "long", "phase3_gaps": []},
        )
        with patch("engines.checklist.runner.STATE_DIR", tmp_path):
            result = run_checklist("xyz:SILVER", "evening", ctx)

        assert result["status"] == "fail"

        item_map = {i["name"]: i for i in result["items"]}

        # SL is SET — should pass
        assert item_map["sl_on_exchange"]["status"] == "pass"

        # TP is SET — should pass
        assert item_map["tp_on_exchange"]["status"] == "pass"

        # 25x vs 3x thesis → FAIL
        assert item_map["leverage_vs_thesis"]["status"] == "fail"
        assert item_map["leverage_vs_thesis"]["data"]["ratio"] == pytest.approx(25.0 / 3.0, rel=0.01)

        # Funding 78% ann → FAIL
        assert item_map["funding_cost"]["status"] == "fail"

        # Sweep score 1 → WARN
        assert item_map["sweep_risk"]["status"] == "warn"

        # Not Friday → weekend_leverage skips/passes
        assert item_map["weekend_leverage"]["status"] in ("pass", "skip")

    def test_result_has_all_evening_keys(self, tmp_path):
        ctx = _make_ctx()
        with patch("engines.checklist.runner.STATE_DIR", tmp_path):
            result = run_checklist("xyz:SILVER", "evening", ctx)

        assert "market" in result
        assert "mode" in result
        assert "timestamp" in result
        assert "status" in result
        assert "score" in result
        assert "items" in result
        for item in result["items"]:
            assert "name" in item
            assert "status" in item
            assert "reason" in item
            assert item["status"] in ("pass", "warn", "fail", "skip")

    def test_no_position_all_skips(self, tmp_path):
        """If market has no position, all position-dependent checks skip."""
        ctx = _make_ctx(positions=[])
        with patch("engines.checklist.runner.STATE_DIR", tmp_path):
            result = run_checklist("xyz:SILVER", "evening", ctx)

        item_map = {i["name"]: i for i in result["items"]}
        # sl_on_exchange, tp_on_exchange, leverage_vs_thesis should skip
        assert item_map["sl_on_exchange"]["status"] == "skip"
        assert item_map["tp_on_exchange"]["status"] == "skip"
        assert item_map["leverage_vs_thesis"]["status"] == "skip"
        # cumulative_risk should pass (no margin)
        assert item_map["cumulative_risk"]["status"] == "pass"
