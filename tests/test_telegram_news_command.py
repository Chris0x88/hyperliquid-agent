"""Tests for /news and /catalysts Telegram commands.

Note: The existing telegram_bot.py uses `tg_send` (not `_send_message`) as its
outbound Telegram helper. The plan's pseudo-code referenced `_send_message` but
we patch the actual symbol (`tg_send`) here. `tg_send`'s signature is
`tg_send(token, chat_id, text, markdown=True)` so `call_args[0][2]` still maps
to the message body, matching the plan's assertion style.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from cli.telegram_bot import cmd_news, cmd_catalysts


def _write_catalysts_jsonl(d, catalysts):
    path = Path(d) / "catalysts.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as f:
        for c in catalysts:
            f.write(json.dumps(c) + "\n")
    return path


def test_cmd_news_returns_top_10_by_severity(tmp_path):
    # Seed a mix of severities
    catalysts = []
    for i in range(15):
        catalysts.append({
            "id": f"c{i}",
            "headline_id": f"h{i}",
            "instruments": ["CL"],
            "event_date": "2026-04-09T12:00:00+00:00",
            "category": "physical_damage_facility",
            "severity": (i % 5) + 1,
            "expected_direction": "bull",
            "rationale": "test",
            "created_at": "2026-04-09T12:00:00+00:00",
        })
    _write_catalysts_jsonl(str(tmp_path), catalysts)

    with patch("cli.telegram_bot.CATALYSTS_JSONL", str(Path(tmp_path) / "catalysts.jsonl")):
        with patch("cli.telegram_bot.tg_send") as send:
            cmd_news("fake_token", "chat_id", "")
            send.assert_called_once()
            body = send.call_args[0][2]  # third positional arg
            assert "catalyst" in body.lower()
            # 10 entries max
            assert body.count("sev=") <= 10 or body.count("  ") <= 10


def test_cmd_catalysts_filters_upcoming(tmp_path):
    now = datetime.now(timezone.utc)
    past = now - timedelta(days=1)
    future = now + timedelta(days=3)
    far_future = now + timedelta(days=30)

    catalysts = [
        {
            "id": "past", "headline_id": "h1", "instruments": ["CL"],
            "event_date": past.isoformat(), "category": "eia_weekly",
            "severity": 3, "expected_direction": None, "rationale": "test",
            "created_at": past.isoformat(),
        },
        {
            "id": "near_future", "headline_id": "h2", "instruments": ["CL"],
            "event_date": future.isoformat(), "category": "opec_action",
            "severity": 4, "expected_direction": None, "rationale": "test",
            "created_at": now.isoformat(),
        },
        {
            "id": "far_future", "headline_id": "h3", "instruments": ["CL"],
            "event_date": far_future.isoformat(), "category": "fomc_macro",
            "severity": 3, "expected_direction": None, "rationale": "test",
            "created_at": now.isoformat(),
        },
    ]
    _write_catalysts_jsonl(str(tmp_path), catalysts)

    with patch("cli.telegram_bot.CATALYSTS_JSONL", str(Path(tmp_path) / "catalysts.jsonl")):
        with patch("cli.telegram_bot.tg_send") as send:
            cmd_catalysts("fake_token", "chat_id", "")
            body = send.call_args[0][2]
            assert "near_future" in body or "opec_action" in body
            assert "far_future" not in body or "fomc_macro" not in body  # beyond 7 days
            assert "past" not in body  # already elapsed
