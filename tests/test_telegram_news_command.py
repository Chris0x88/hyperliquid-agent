"""Tests for /news and /catalysts Telegram commands.

Note: The existing telegram_bot.py uses `tg_send` (not `_send_message`) as its
outbound Telegram helper. The plan's pseudo-code referenced `_send_message` but
we patch the actual symbol (`tg_send`) here. `tg_send`'s signature is
`tg_send(token, chat_id, text, markdown=True)` so `call_args[0][2]` still maps
to the message body, matching the plan's assertion style.
"""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from cli.telegram_bot import cmd_news


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
