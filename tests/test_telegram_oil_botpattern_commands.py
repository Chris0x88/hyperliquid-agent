"""Tests for /oilbot, /oilbotjournal, /oilbotreviewai — sub-system 5."""
import json
from pathlib import Path
from unittest.mock import patch

from telegram.bot import cmd_oilbot, cmd_oilbotjournal, cmd_oilbotreviewai


def test_cmd_oilbot_reports_kill_switch_off(tmp_path):
    cfg_path = tmp_path / "cfg.json"
    cfg_path.write_text(json.dumps({
        "enabled": False,
        "short_legs_enabled": False,
        "instruments": ["BRENTOIL", "CL"],
        "drawdown_brakes": {
            "daily_max_loss_pct": 3.0,
            "weekly_max_loss_pct": 8.0,
            "monthly_max_loss_pct": 15.0,
        },
    }))
    state_path = tmp_path / "state.json"
    with patch("telegram.bot.OIL_BOTPATTERN_CONFIG_JSON", str(cfg_path)):
        with patch("telegram.bot.OIL_BOTPATTERN_STATE_JSON", str(state_path)):
            with patch("telegram.bot.tg_send") as send:
                cmd_oilbot("tok", "chat", "")
                body = send.call_args[0][2]
                assert "🔴 OFF" in body
                assert "BRENTOIL" in body
                assert "Circuit breakers" in body


def test_cmd_oilbot_shows_open_position(tmp_path):
    cfg_path = tmp_path / "cfg.json"
    cfg_path.write_text(json.dumps({
        "enabled": True,
        "short_legs_enabled": False,
        "instruments": ["BRENTOIL"],
        "drawdown_brakes": {"daily_max_loss_pct": 3, "weekly_max_loss_pct": 8, "monthly_max_loss_pct": 15},
    }))
    state_path = tmp_path / "state.json"
    state_path.write_text(json.dumps({
        "open_positions": {
            "BRENTOIL": {
                "side": "long", "entry_ts": "2026-04-09T20:00:00+00:00",
                "entry_price": 67.42, "size": 1000.0, "leverage": 5.0,
                "cumulative_funding_usd": 250.0, "realised_pnl_today_usd": 0.0,
            }
        },
        "daily_realised_pnl_usd": 120.0, "weekly_realised_pnl_usd": 500.0,
        "monthly_realised_pnl_usd": 1200.0,
        "daily_window_start": "2026-04-09", "weekly_window_start": "2026-W15",
        "monthly_window_start": "2026-04",
        "daily_brake_tripped_at": None, "weekly_brake_tripped_at": None,
        "monthly_brake_tripped_at": None, "brake_cleared_at": None,
        "enabled_since": "2026-04-09T18:00:00+00:00",
    }))
    with patch("telegram.bot.OIL_BOTPATTERN_CONFIG_JSON", str(cfg_path)):
        with patch("telegram.bot.OIL_BOTPATTERN_STATE_JSON", str(state_path)):
            with patch("telegram.bot.tg_send") as send:
                cmd_oilbot("tok", "chat", "")
                body = send.call_args[0][2]
                assert "LONG BRENTOIL" in body
                assert "67.42" in body
                assert "$67,420" in body  # notional
                assert "funding paid" in body


def test_cmd_oilbotjournal_no_data(tmp_path):
    with patch("telegram.bot.OIL_BOTPATTERN_DECISIONS_JSONL", str(tmp_path / "d.jsonl")):
        with patch("telegram.bot.tg_send") as send:
            cmd_oilbotjournal("tok", "chat", "")
            body = send.call_args[0][2]
            assert "No oil_botpattern decisions" in body


def test_cmd_oilbotjournal_renders(tmp_path):
    path = tmp_path / "d.jsonl"
    decisions = [
        {
            "id": "BRENTOIL_1", "instrument": "BRENTOIL",
            "decided_at": "2026-04-09T22:30:00+00:00",
            "direction": "long", "action": "open", "edge": 0.78,
            "classification": "informed_move", "classifier_confidence": 0.78,
            "thesis_conviction": 0.6, "recent_outcome_bias": 0.0,
            "sizing": {}, "gate_results": [{"name": "classification", "passed": True, "reason": "ok"}],
            "notes": "",
        },
        {
            "id": "BRENTOIL_2", "instrument": "BRENTOIL",
            "decided_at": "2026-04-09T22:00:00+00:00",
            "direction": "short", "action": "skip", "edge": 0.72,
            "classification": "bot_driven_overextension", "classifier_confidence": 0.72,
            "thesis_conviction": 0.0, "recent_outcome_bias": 0.0,
            "sizing": {}, "gate_results": [
                {"name": "short_grace_period", "passed": False, "reason": "grace period: 100s / 3600s"},
            ],
            "notes": "",
        },
    ]
    with path.open("w") as f:
        for d in decisions:
            f.write(json.dumps(d) + "\n")
    with patch("telegram.bot.OIL_BOTPATTERN_DECISIONS_JSONL", str(path)):
        with patch("telegram.bot.tg_send") as send:
            cmd_oilbotjournal("tok", "chat", "")
            body = send.call_args[0][2]
            assert "open" in body
            assert "skip" in body
            assert "short_grace_period" in body
            # Most recent first
            assert body.index("22:30") < body.index("22:00")


def test_cmd_oilbotreviewai_no_data(tmp_path):
    with patch("telegram.bot.OIL_BOTPATTERN_DECISIONS_JSONL", str(tmp_path / "nope.jsonl")):
        with patch("telegram.bot.tg_send") as send:
            cmd_oilbotreviewai("tok", "chat", "")
            body = send.call_args[0][2]
            assert "No decisions" in body


def test_cmd_oilbotreviewai_routes_to_agent(tmp_path):
    path = tmp_path / "d.jsonl"
    path.write_text(json.dumps({
        "id": "x", "instrument": "BRENTOIL",
        "decided_at": "2026-04-09T22:30:00+00:00",
        "direction": "long", "action": "open", "edge": 0.8,
        "classification": "informed_move", "classifier_confidence": 0.8,
        "thesis_conviction": 0.0, "recent_outcome_bias": 0.0,
        "sizing": {}, "gate_results": [], "notes": "",
    }) + "\n")
    with patch("telegram.bot.OIL_BOTPATTERN_DECISIONS_JSONL", str(path)):
        with patch("telegram.agent.handle_ai_message") as handle:
            cmd_oilbotreviewai("tok", "chat", "")
            handle.assert_called_once()
            msg = handle.call_args[0][2]
            assert "Review the last 1" in msg
            assert "BRENTOIL" in msg


def test_handlers_registered():
    from telegram.bot import HANDLERS
    assert HANDLERS["/oilbot"] is cmd_oilbot
    assert HANDLERS["oilbot"] is cmd_oilbot
    assert HANDLERS["/oilbotjournal"] is cmd_oilbotjournal
    assert HANDLERS["/oilbotreviewai"] is cmd_oilbotreviewai
