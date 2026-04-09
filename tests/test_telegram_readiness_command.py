"""Tests for /readiness — sub-system 5 activation preflight checklist."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from cli.telegram_commands.readiness import (
    check_bot_classifier,
    check_catalyst_feed,
    check_drawdown_brakes,
    check_heatmap,
    check_master_switch,
    check_risk_caps,
    check_supply_ledger,
    check_thesis,
    cmd_readiness,
    compute_readiness,
)


UTC = timezone.utc


def _patch_paths(tmp: Path):
    patchers = [
        patch("cli.telegram_commands.readiness.CATALYSTS_JSONL", str(tmp / "catalysts.jsonl")),
        patch("cli.telegram_commands.readiness.SUPPLY_STATE_JSON", str(tmp / "supply.json")),
        patch("cli.telegram_commands.readiness.HEATMAP_ZONES_JSONL", str(tmp / "zones.jsonl")),
        patch("cli.telegram_commands.readiness.BOT_PATTERNS_JSONL", str(tmp / "bot_patterns.jsonl")),
        patch("cli.telegram_commands.readiness.BRENTOIL_THESIS_JSON", str(tmp / "thesis.json")),
        patch("cli.telegram_commands.readiness.RISK_CAPS_JSON", str(tmp / "risk_caps.json")),
        patch("cli.telegram_commands.readiness.OIL_BOTPATTERN_CONFIG_JSON", str(tmp / "oil_botpattern.json")),
        patch("cli.telegram_commands.readiness.OIL_BOTPATTERN_STATE_JSON", str(tmp / "state.json")),
    ]
    for p in patchers:
        p.start()
    return patchers


def _stop(patchers):
    for p in patchers:
        p.stop()


def _now() -> datetime:
    return datetime(2026, 4, 9, 10, 0, tzinfo=UTC)


def _iso(h_ago: float) -> str:
    return (_now() - timedelta(hours=h_ago)).isoformat()


# ---------------------------------------------------------------------------
# Individual checks
# ---------------------------------------------------------------------------

def test_catalyst_check_missing_file(tmp_path):
    patchers = _patch_paths(tmp_path)
    try:
        sym, _name, verdict, sev = check_catalyst_feed(_now())
        assert sym == "🔴"
        assert "no data" in verdict
        assert sev == "red"
    finally:
        _stop(patchers)


def test_catalyst_check_fresh(tmp_path):
    patchers = _patch_paths(tmp_path)
    try:
        (tmp_path / "catalysts.jsonl").write_text(
            json.dumps({"published_at": _iso(2)}) + "\n"
        )
        sym, _name, verdict, sev = check_catalyst_feed(_now())
        assert sym == "🟢"
        assert sev == "green"
    finally:
        _stop(patchers)


def test_catalyst_check_stale(tmp_path):
    patchers = _patch_paths(tmp_path)
    try:
        (tmp_path / "catalysts.jsonl").write_text(
            json.dumps({"published_at": _iso(20)}) + "\n"
        )
        sym, _name, _verdict, sev = check_catalyst_feed(_now())
        assert sym == "🟡"
        assert sev == "yellow"
    finally:
        _stop(patchers)


def test_catalyst_check_very_stale(tmp_path):
    patchers = _patch_paths(tmp_path)
    try:
        (tmp_path / "catalysts.jsonl").write_text(
            json.dumps({"published_at": _iso(48)}) + "\n"
        )
        sym, _name, _verdict, sev = check_catalyst_feed(_now())
        assert sym == "🔴"
        assert sev == "red"
    finally:
        _stop(patchers)


def test_supply_ledger_missing(tmp_path):
    patchers = _patch_paths(tmp_path)
    try:
        _, _, _, sev = check_supply_ledger(_now())
        assert sev == "red"
    finally:
        _stop(patchers)


def test_supply_ledger_fresh(tmp_path):
    patchers = _patch_paths(tmp_path)
    try:
        (tmp_path / "supply.json").write_text(json.dumps({
            "computed_at": _iso(6),
            "active_disruption_count": 3,
        }))
        _, _, verdict, sev = check_supply_ledger(_now())
        assert sev == "green"
        assert "3 active" in verdict
    finally:
        _stop(patchers)


def test_heatmap_fresh(tmp_path):
    patchers = _patch_paths(tmp_path)
    try:
        (tmp_path / "zones.jsonl").write_text(
            json.dumps({"detected_at": _iso(2)}) + "\n"
        )
        _, _, _, sev = check_heatmap(_now())
        assert sev == "green"
    finally:
        _stop(patchers)


def test_bot_classifier_fresh(tmp_path):
    patchers = _patch_paths(tmp_path)
    try:
        (tmp_path / "bot_patterns.jsonl").write_text(
            json.dumps({"detected_at": _iso(1)}) + "\n"
        )
        _, _, _, sev = check_bot_classifier(_now())
        assert sev == "green"
    finally:
        _stop(patchers)


def test_bot_classifier_silent(tmp_path):
    patchers = _patch_paths(tmp_path)
    try:
        (tmp_path / "bot_patterns.jsonl").write_text(
            json.dumps({"detected_at": _iso(60)}) + "\n"
        )
        _, _, _, sev = check_bot_classifier(_now())
        assert sev == "red"
    finally:
        _stop(patchers)


def test_thesis_missing_is_yellow(tmp_path):
    patchers = _patch_paths(tmp_path)
    try:
        _, _, _, sev = check_thesis(_now())
        assert sev == "yellow"  # thesis optional, yellow not red
    finally:
        _stop(patchers)


def test_thesis_fresh(tmp_path):
    patchers = _patch_paths(tmp_path)
    try:
        (tmp_path / "thesis.json").write_text(json.dumps({
            "updated_at": _iso(12),
            "conviction": 0.7,
        }))
        _, _, verdict, sev = check_thesis(_now())
        assert sev == "green"
        assert "0.7" in verdict
    finally:
        _stop(patchers)


def test_thesis_stale_is_red(tmp_path):
    patchers = _patch_paths(tmp_path)
    try:
        (tmp_path / "thesis.json").write_text(json.dumps({
            "updated_at": _iso(200),
            "conviction": 0.7,
        }))
        _, _, _, sev = check_thesis(_now())
        assert sev == "red"
    finally:
        _stop(patchers)


def test_risk_caps_missing(tmp_path):
    patchers = _patch_paths(tmp_path)
    try:
        _, _, _, sev = check_risk_caps()
        assert sev == "red"
    finally:
        _stop(patchers)


def test_risk_caps_configured(tmp_path):
    patchers = _patch_paths(tmp_path)
    try:
        (tmp_path / "risk_caps.json").write_text(json.dumps({
            "oil_botpattern": {
                "BRENTOIL": {"sizing_multiplier": 1.0},
                "CL": {"sizing_multiplier": 0.6},
            }
        }))
        _, _, verdict, sev = check_risk_caps()
        assert sev == "green"
        assert "BRENTOIL" in verdict
        assert "CL" in verdict
    finally:
        _stop(patchers)


def test_drawdown_brakes_clean_no_state(tmp_path):
    patchers = _patch_paths(tmp_path)
    try:
        _, _, _, sev = check_drawdown_brakes()
        assert sev == "green"
    finally:
        _stop(patchers)


def test_drawdown_brakes_tripped(tmp_path):
    patchers = _patch_paths(tmp_path)
    try:
        (tmp_path / "state.json").write_text(json.dumps({
            "daily_brake_tripped_at": "2026-04-09T08:00:00+00:00",
            "brake_cleared_at": None,
        }))
        _, _, verdict, sev = check_drawdown_brakes()
        assert sev == "red"
        assert "TRIPPED" in verdict
    finally:
        _stop(patchers)


def test_drawdown_brakes_cleared(tmp_path):
    patchers = _patch_paths(tmp_path)
    try:
        (tmp_path / "state.json").write_text(json.dumps({
            "daily_brake_tripped_at": "2026-04-09T08:00:00+00:00",
            "brake_cleared_at": "2026-04-09T08:30:00+00:00",
        }))
        _, _, _, sev = check_drawdown_brakes()
        assert sev == "yellow"
    finally:
        _stop(patchers)


def test_master_switch_off_is_green(tmp_path):
    """Master switch OFF is the STARTING state — green because it means
    we're ready to promote, not because we're active."""
    patchers = _patch_paths(tmp_path)
    try:
        (tmp_path / "oil_botpattern.json").write_text(json.dumps({
            "enabled": False,
        }))
        _, _, _, sev = check_master_switch()
        assert sev == "green"
    finally:
        _stop(patchers)


def test_master_switch_shadow_is_yellow(tmp_path):
    patchers = _patch_paths(tmp_path)
    try:
        (tmp_path / "oil_botpattern.json").write_text(json.dumps({
            "enabled": True, "decisions_only": True,
        }))
        _, _, verdict, sev = check_master_switch()
        assert sev == "yellow"
        assert "SHADOW" in verdict
    finally:
        _stop(patchers)


def test_master_switch_live_is_red(tmp_path):
    patchers = _patch_paths(tmp_path)
    try:
        (tmp_path / "oil_botpattern.json").write_text(json.dumps({
            "enabled": True, "decisions_only": False,
        }))
        _, _, verdict, sev = check_master_switch()
        assert sev == "red"
        assert "LIVE" in verdict
    finally:
        _stop(patchers)


# ---------------------------------------------------------------------------
# compute_readiness driver
# ---------------------------------------------------------------------------

def test_compute_readiness_all_green(tmp_path):
    patchers = _patch_paths(tmp_path)
    try:
        (tmp_path / "oil_botpattern.json").write_text(json.dumps({"enabled": False}))
        (tmp_path / "catalysts.jsonl").write_text(json.dumps({"published_at": _iso(2)}) + "\n")
        (tmp_path / "supply.json").write_text(json.dumps({"computed_at": _iso(4), "active_disruption_count": 2}))
        (tmp_path / "zones.jsonl").write_text(json.dumps({"detected_at": _iso(1)}) + "\n")
        (tmp_path / "bot_patterns.jsonl").write_text(json.dumps({"detected_at": _iso(1)}) + "\n")
        (tmp_path / "thesis.json").write_text(json.dumps({"updated_at": _iso(24), "conviction": 0.7}))
        (tmp_path / "risk_caps.json").write_text(json.dumps({
            "oil_botpattern": {"BRENTOIL": {}, "CL": {}}
        }))
        # state.json intentionally missing — clean brake

        _results, overall = compute_readiness(_now())
        assert "🟢 *GO*" in overall
    finally:
        _stop(patchers)


def test_compute_readiness_yellow_on_stale_catalyst(tmp_path):
    patchers = _patch_paths(tmp_path)
    try:
        (tmp_path / "oil_botpattern.json").write_text(json.dumps({"enabled": False}))
        (tmp_path / "catalysts.jsonl").write_text(json.dumps({"published_at": _iso(18)}) + "\n")
        (tmp_path / "supply.json").write_text(json.dumps({"computed_at": _iso(4), "active_disruption_count": 1}))
        (tmp_path / "zones.jsonl").write_text(json.dumps({"detected_at": _iso(1)}) + "\n")
        (tmp_path / "bot_patterns.jsonl").write_text(json.dumps({"detected_at": _iso(1)}) + "\n")
        (tmp_path / "thesis.json").write_text(json.dumps({"updated_at": _iso(24), "conviction": 0.7}))
        (tmp_path / "risk_caps.json").write_text(json.dumps({"oil_botpattern": {"BRENTOIL": {}}}))

        _results, overall = compute_readiness(_now())
        assert "PROCEED WITH CAUTION" in overall
    finally:
        _stop(patchers)


def test_compute_readiness_red_on_missing_risk_caps(tmp_path):
    patchers = _patch_paths(tmp_path)
    try:
        (tmp_path / "oil_botpattern.json").write_text(json.dumps({"enabled": False}))
        (tmp_path / "catalysts.jsonl").write_text(json.dumps({"published_at": _iso(2)}) + "\n")
        (tmp_path / "supply.json").write_text(json.dumps({"computed_at": _iso(4), "active_disruption_count": 1}))
        (tmp_path / "zones.jsonl").write_text(json.dumps({"detected_at": _iso(1)}) + "\n")
        (tmp_path / "bot_patterns.jsonl").write_text(json.dumps({"detected_at": _iso(1)}) + "\n")
        (tmp_path / "thesis.json").write_text(json.dumps({"updated_at": _iso(24), "conviction": 0.7}))
        # risk_caps.json missing

        _results, overall = compute_readiness(_now())
        assert "DO NOT ACTIVATE" in overall
    finally:
        _stop(patchers)


# ---------------------------------------------------------------------------
# /readiness command
# ---------------------------------------------------------------------------

def test_cmd_readiness_renders(tmp_path):
    patchers = _patch_paths(tmp_path)
    try:
        (tmp_path / "oil_botpattern.json").write_text(json.dumps({"enabled": False}))
        with patch("cli.telegram_bot.tg_send") as send:
            cmd_readiness("tok", "chat", "")
            body = send.call_args[0][2]
            assert "activation preflight" in body
            assert "Sub-system 5 config" in body
            assert "Catalyst feed" in body
            assert "Risk caps" in body
    finally:
        _stop(patchers)


# ---------------------------------------------------------------------------
# HANDLERS registration
# ---------------------------------------------------------------------------

def test_readiness_registered_in_handlers():
    from cli.telegram_bot import HANDLERS
    assert "/readiness" in HANDLERS
    assert "readiness" in HANDLERS


def test_readiness_in_help():
    from cli.telegram_bot import cmd_help
    with patch("cli.telegram_bot.tg_send") as send:
        cmd_help("tok", "chat", "")
        body = send.call_args[0][2]
        assert "/readiness" in body
