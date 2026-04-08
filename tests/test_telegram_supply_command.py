"""Tests for /supply, /disruptions, /disrupt, /disrupt-update Telegram commands."""
import json
from pathlib import Path
from unittest.mock import patch

from cli.telegram_bot import cmd_supply


def _write_state(d, payload):
    p = Path(d) / "state.json"
    p.write_text(json.dumps(payload))
    return p


# ── /supply ──────────────────────────────────────────────────────

def test_cmd_supply_renders_state(tmp_path):
    _write_state(str(tmp_path), {
        "computed_at": "2026-04-09T06:15:00+00:00",
        "total_offline_bpd": 2400000.0,
        "total_offline_mcfd": 180.0,
        "by_region": {"russia": 1200000.0, "red_sea": 800000.0},
        "by_facility_type": {"refinery": 1450000.0, "ship": 200000.0},
        "active_chokepoints": ["hormuz_strait"],
        "active_disruption_count": 14,
        "high_confidence_count": 6,
    })
    with patch("cli.telegram_bot.SUPPLY_STATE_JSON", str(Path(tmp_path) / "state.json")):
        with patch("cli.telegram_bot.tg_send") as send:
            cmd_supply("tok", "chat", "")
            send.assert_called_once()
            body = send.call_args[0][2]
            assert "2,400,000 bpd" in body or "2400000" in body
            assert "russia" in body
            assert "hormuz_strait" in body


def test_cmd_supply_missing_state(tmp_path):
    with patch("cli.telegram_bot.SUPPLY_STATE_JSON", str(Path(tmp_path) / "no.json")):
        with patch("cli.telegram_bot.tg_send") as send:
            cmd_supply("tok", "chat", "")
            body = send.call_args[0][2]
            assert "no supply state" in body.lower() or "not yet" in body.lower()
