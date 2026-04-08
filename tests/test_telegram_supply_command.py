"""Tests for /supply, /disruptions, /disrupt, /disrupt-update Telegram commands."""
import json
from pathlib import Path
from unittest.mock import patch

from cli.telegram_bot import cmd_supply, cmd_disruptions, cmd_disrupt, cmd_disrupt_update


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


# ── /disruptions ─────────────────────────────────────────────────

def test_cmd_disruptions_lists_active(tmp_path):
    path = Path(tmp_path) / "d.jsonl"
    with path.open("w") as f:
        f.write(json.dumps({
            "id": "d1", "source": "manual", "source_ref": "u",
            "facility_name": "Volgograd refinery", "facility_type": "refinery",
            "location": "russia", "region": "russia",
            "volume_offline": 200000.0, "volume_unit": "bpd",
            "incident_date": "2026-04-08T00:00:00+00:00",
            "expected_recovery": None,
            "confidence": 4, "status": "active",
            "instruments": ["CL"], "notes": "drone strike",
            "created_at": "2026-04-09T00:00:00+00:00",
            "updated_at": "2026-04-09T00:00:00+00:00",
        }) + "\n")
        f.write(json.dumps({
            "id": "d2", "source": "manual", "source_ref": "u",
            "facility_name": "Test restored", "facility_type": "refinery",
            "location": "russia", "region": "russia",
            "volume_offline": 50000.0, "volume_unit": "bpd",
            "incident_date": "2026-04-08T00:00:00+00:00",
            "expected_recovery": None,
            "confidence": 3, "status": "restored",
            "instruments": ["CL"], "notes": "",
            "created_at": "2026-04-09T00:00:00+00:00",
            "updated_at": "2026-04-09T00:00:00+00:00",
        }) + "\n")
    with patch("cli.telegram_bot.SUPPLY_DISRUPTIONS_JSONL", str(path)):
        with patch("cli.telegram_bot.tg_send") as send:
            cmd_disruptions("tok", "chat", "")
            body = send.call_args[0][2]
            assert "Volgograd refinery" in body
            assert "Test restored" not in body


# ── /disrupt ─────────────────────────────────────────────────────

def test_cmd_disrupt_appends_row(tmp_path):
    path = Path(tmp_path) / "d.jsonl"
    with patch("cli.telegram_bot.SUPPLY_DISRUPTIONS_JSONL", str(path)):
        with patch("cli.telegram_bot.tg_send"):
            cmd_disrupt("tok", "chat", 'refinery Volgograd 200000 bpd active 2026-04-08 "drone strike"')
            assert path.exists()
            rows = [json.loads(l) for l in path.read_text().strip().split("\n")]
            assert len(rows) == 1
            assert rows[0]["facility_type"] == "refinery"
            assert rows[0]["location"] == "Volgograd"
            assert rows[0]["volume_offline"] == 200000.0
            assert rows[0]["status"] == "active"


def test_cmd_disrupt_rejects_empty():
    with patch("cli.telegram_bot.tg_send") as send:
        cmd_disrupt("tok", "chat", "")
        body = send.call_args[0][2]
        assert "usage" in body.lower() or "format" in body.lower()


# ── /disrupt-update ──────────────────────────────────────────────

def test_cmd_disrupt_update_appends_new_row(tmp_path):
    path = Path(tmp_path) / "d.jsonl"
    original = {
        "id": "abc12345",
        "source": "manual", "source_ref": "u",
        "facility_name": "Volgograd refinery", "facility_type": "refinery",
        "location": "Volgograd", "region": "russia",
        "volume_offline": 200000.0, "volume_unit": "bpd",
        "incident_date": "2026-04-08T00:00:00+00:00",
        "expected_recovery": None,
        "confidence": 4, "status": "active",
        "instruments": ["CL"], "notes": "drone strike",
        "created_at": "2026-04-09T00:00:00+00:00",
        "updated_at": "2026-04-09T00:00:00+00:00",
    }
    with path.open("w") as f:
        f.write(json.dumps(original) + "\n")

    with patch("cli.telegram_bot.SUPPLY_DISRUPTIONS_JSONL", str(path)):
        with patch("cli.telegram_bot.tg_send"):
            cmd_disrupt_update("tok", "chat", "abc12345 status=restored")

    rows = [json.loads(l) for l in path.read_text().strip().split("\n")]
    assert len(rows) == 2
    assert rows[-1]["id"] == "abc12345"
    assert rows[-1]["status"] == "restored"
