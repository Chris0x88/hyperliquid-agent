"""Tests for the /botpatterns Telegram command — sub-system 4."""
import json
from pathlib import Path
from unittest.mock import patch

from cli.telegram_bot import cmd_botpatterns


def _row(detected_at="2026-04-09T22:30:00+00:00", classification="bot_driven_overextension",
         conf=0.78, instrument="BRENTOIL"):
    return {
        "id": f"{instrument}_{detected_at}",
        "instrument": instrument,
        "detected_at": detected_at,
        "lookback_minutes": 60,
        "classification": classification,
        "confidence": conf,
        "direction": "down",
        "price_at_detection": 67.42,
        "price_change_pct": -1.6,
        "signals": ["cascade_long_sev3", "no_high_sev_catalyst_in_24h"],
        "notes": "test",
    }


def _write_patterns(path: Path, rows: list[dict]) -> None:
    with path.open("w") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")


def test_no_data(tmp_path):
    with patch("cli.telegram_bot.BOT_PATTERNS_JSONL", str(tmp_path / "p.jsonl")):
        with patch("cli.telegram_bot.tg_send") as send:
            cmd_botpatterns("tok", "chat", "")
            body = send.call_args[0][2]
            assert "No bot-pattern" in body or "still booting" in body


def test_renders_patterns(tmp_path):
    p = tmp_path / "p.jsonl"
    _write_patterns(p, [
        _row(detected_at="2026-04-09T22:00:00+00:00"),
        _row(detected_at="2026-04-09T22:30:00+00:00", classification="informed_move", conf=0.7),
    ])
    with patch("cli.telegram_bot.BOT_PATTERNS_JSONL", str(p)):
        with patch("cli.telegram_bot.tg_send") as send:
            cmd_botpatterns("tok", "chat", "")
            body = send.call_args[0][2]
            assert "BRENTOIL" in body
            assert "bot_driven_overextension" in body
            assert "informed_move" in body
            assert "cascade_long_sev3" in body


def test_sorts_most_recent_first(tmp_path):
    p = tmp_path / "p.jsonl"
    _write_patterns(p, [
        _row(detected_at="2026-04-09T20:00:00+00:00"),
        _row(detected_at="2026-04-09T22:30:00+00:00", classification="informed_move"),
    ])
    with patch("cli.telegram_bot.BOT_PATTERNS_JSONL", str(p)):
        with patch("cli.telegram_bot.tg_send") as send:
            cmd_botpatterns("tok", "chat", "")
            body = send.call_args[0][2]
            # 22:30 line must come before 20:00 line
            assert body.index("22:30") < body.index("20:00")


def test_filters_by_instrument(tmp_path):
    p = tmp_path / "p.jsonl"
    _write_patterns(p, [
        _row(instrument="BRENTOIL"),
        _row(instrument="GOLD"),
    ])
    with patch("cli.telegram_bot.BOT_PATTERNS_JSONL", str(p)):
        with patch("cli.telegram_bot.tg_send") as send:
            cmd_botpatterns("tok", "chat", "GOLD")
            body = send.call_args[0][2]
            assert "GOLD" in body


def test_unknown_instrument(tmp_path):
    p = tmp_path / "p.jsonl"
    _write_patterns(p, [_row()])
    with patch("cli.telegram_bot.BOT_PATTERNS_JSONL", str(p)):
        with patch("cli.telegram_bot.tg_send") as send:
            cmd_botpatterns("tok", "chat", "SILVER")
            body = send.call_args[0][2]
            assert "No classifications" in body


def test_limit_argument(tmp_path):
    p = tmp_path / "p.jsonl"
    rows = [_row(detected_at=f"2026-04-09T{20+i:02d}:00:00+00:00") for i in range(5)]
    _write_patterns(p, rows)
    with patch("cli.telegram_bot.BOT_PATTERNS_JSONL", str(p)):
        with patch("cli.telegram_bot.tg_send") as send:
            cmd_botpatterns("tok", "chat", "BRENTOIL 2")
            body = send.call_args[0][2]
            assert "last 2" in body


def test_registered_in_handlers():
    from cli.telegram_bot import HANDLERS
    assert HANDLERS.get("/botpatterns") is cmd_botpatterns
    assert HANDLERS.get("botpatterns") is cmd_botpatterns
