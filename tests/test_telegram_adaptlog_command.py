"""Tests for /adaptlog — adaptive evaluator log query."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from cli.telegram_commands.adaptlog import (
    _filter_rows,
    _load_log_rows,
    cmd_adaptlog,
    parse_args,
)


UTC = timezone.utc


def _patch_path(tmp: Path):
    p = patch("cli.telegram_commands.adaptlog.ADAPTIVE_LOG_JSONL",
              str(tmp / "adaptive_log.jsonl"))
    p.start()
    return p


def _row(**overrides) -> dict:
    base = {
        "logged_at": "2026-04-09T10:00:00+00:00",
        "mode": "shadow",
        "position": {
            "instrument": "BRENTOIL",
            "side": "long",
            "entry_ts": "2026-04-09T08:00:00+00:00",
            "entry_price": 67.00,
            "expected_reach_price": 70.35,
            "entry_classification": "bot_driven_overextension",
        },
        "snapshot": {
            "current_price": 68.50,
            "latest_pattern_classification": "bot_driven_overextension",
        },
        "decision": {
            "action": "trail_breakeven",
            "reason": "progressed past 50%",
            "hours_held": 2.0,
            "price_progress": 0.45,
            "time_progress": 0.042,
            "velocity_ratio": 10.7,
            "new_stop_price": 67.00,
        },
    }
    base.update(overrides)
    return base


def _write_rows(tmp: Path, rows: list[dict]):
    path = tmp / "adaptive_log.jsonl"
    path.write_text("".join(json.dumps(r) + "\n" for r in rows))


# ---------------------------------------------------------------------------
# parse_args
# ---------------------------------------------------------------------------

def test_parse_args_defaults():
    limit, action, mode, inst = parse_args("")
    assert limit == 10
    assert action is None
    assert mode is None
    assert inst is None


def test_parse_args_limit():
    limit, *_ = parse_args("25")
    assert limit == 25


def test_parse_args_limit_clamped():
    # Out-of-range integer treated as instrument
    limit, _a, _m, inst = parse_args("500")
    assert limit == 10  # default
    assert inst == "500"


def test_parse_args_action_exits():
    _l, action, _m, _i = parse_args("exits")
    assert action == "exit"


def test_parse_args_action_trails():
    _l, action, _m, _i = parse_args("trails")
    assert action == "trail_breakeven"


def test_parse_args_action_tightens():
    _l, action, _m, _i = parse_args("tightens")
    assert action == "tighten_stop"


def test_parse_args_mode_live():
    _l, _a, mode, _i = parse_args("live")
    assert mode == "live"


def test_parse_args_mode_shadow():
    _l, _a, mode, _i = parse_args("shadow")
    assert mode == "shadow"


def test_parse_args_instrument_uppercased():
    _l, _a, _m, inst = parse_args("brentoil")
    assert inst == "BRENTOIL"


def test_parse_args_combined():
    limit, action, mode, inst = parse_args("25 exits live BRENTOIL")
    assert limit == 25
    assert action == "exit"
    assert mode == "live"
    assert inst == "BRENTOIL"


# ---------------------------------------------------------------------------
# _filter_rows
# ---------------------------------------------------------------------------

def test_filter_by_action():
    rows = [
        _row(decision={"action": "exit", "reason": "x", "hours_held": 0,
                        "price_progress": 0, "time_progress": 0, "velocity_ratio": 0}),
        _row(decision={"action": "hold", "reason": "x", "hours_held": 0,
                        "price_progress": 0, "time_progress": 0, "velocity_ratio": 0}),
    ]
    result = _filter_rows(rows, action="exit")
    assert len(result) == 1
    assert result[0]["decision"]["action"] == "exit"


def test_filter_by_mode():
    rows = [_row(mode="shadow"), _row(mode="live")]
    result = _filter_rows(rows, mode="live")
    assert len(result) == 1
    assert result[0]["mode"] == "live"


def test_filter_by_instrument():
    rows = [
        _row(position={**_row()["position"], "instrument": "BRENTOIL"}),
        _row(position={**_row()["position"], "instrument": "CL"}),
    ]
    result = _filter_rows(rows, instrument="CL")
    assert len(result) == 1
    assert result[0]["position"]["instrument"] == "CL"


def test_filter_combined():
    rows = [
        _row(mode="live", position={**_row()["position"], "instrument": "BRENTOIL"}),
        _row(mode="shadow", position={**_row()["position"], "instrument": "BRENTOIL"}),
        _row(mode="live", position={**_row()["position"], "instrument": "CL"}),
    ]
    result = _filter_rows(rows, mode="live", instrument="BRENTOIL")
    assert len(result) == 1


# ---------------------------------------------------------------------------
# _load_log_rows
# ---------------------------------------------------------------------------

def test_load_missing_file_returns_empty(tmp_path):
    assert _load_log_rows(str(tmp_path / "nope.jsonl")) == []


def test_load_valid_rows(tmp_path):
    _write_rows(tmp_path, [_row(), _row()])
    rows = _load_log_rows(str(tmp_path / "adaptive_log.jsonl"))
    assert len(rows) == 2


def test_load_tolerates_bad_lines(tmp_path):
    path = tmp_path / "adaptive_log.jsonl"
    path.write_text(json.dumps(_row()) + "\n{not json\n" + json.dumps(_row()) + "\n")
    rows = _load_log_rows(str(path))
    assert len(rows) == 2


# ---------------------------------------------------------------------------
# cmd_adaptlog
# ---------------------------------------------------------------------------

def test_adaptlog_empty(tmp_path):
    p = _patch_path(tmp_path)
    try:
        with patch("cli.telegram_bot.tg_send") as send:
            cmd_adaptlog("tok", "chat", "")
            body = send.call_args[0][2]
            assert "No decisions logged" in body
    finally:
        p.stop()


def test_adaptlog_renders_rows(tmp_path):
    p = _patch_path(tmp_path)
    try:
        rows = [
            _row(logged_at="2026-04-09T09:00:00+00:00",
                  decision={**_row()["decision"], "action": "exit", "reason": "drift"}),
            _row(logged_at="2026-04-09T10:00:00+00:00",
                  decision={**_row()["decision"], "action": "trail_breakeven"}),
        ]
        _write_rows(tmp_path, rows)
        with patch("cli.telegram_bot.tg_send") as send:
            cmd_adaptlog("tok", "chat", "")
            body = send.call_args[0][2]
            assert "Adaptive log" in body
            assert "exit" in body
            assert "trail_breakeven" in body
            assert "BRENTOIL" in body
    finally:
        p.stop()


def test_adaptlog_filter_exits_only(tmp_path):
    p = _patch_path(tmp_path)
    try:
        rows = [
            _row(decision={**_row()["decision"], "action": "trail_breakeven"}),
            _row(decision={**_row()["decision"], "action": "exit", "reason": "x"}),
            _row(decision={**_row()["decision"], "action": "hold"}),
        ]
        _write_rows(tmp_path, rows)
        with patch("cli.telegram_bot.tg_send") as send:
            cmd_adaptlog("tok", "chat", "exits")
            body = send.call_args[0][2]
            assert "exit" in body
            assert "trail_breakeven" not in body
            assert "hold" not in body
    finally:
        p.stop()


def test_adaptlog_filter_instrument(tmp_path):
    p = _patch_path(tmp_path)
    try:
        rows = [
            _row(position={**_row()["position"], "instrument": "BRENTOIL"}),
            _row(position={**_row()["position"], "instrument": "CL"}),
        ]
        _write_rows(tmp_path, rows)
        with patch("cli.telegram_bot.tg_send") as send:
            cmd_adaptlog("tok", "chat", "CL")
            body = send.call_args[0][2]
            assert "CL" in body
            assert body.count("BRENTOIL") == 0
    finally:
        p.stop()


def test_adaptlog_filter_mode_live(tmp_path):
    p = _patch_path(tmp_path)
    try:
        rows = [
            _row(mode="live"),
            _row(mode="shadow"),
        ]
        _write_rows(tmp_path, rows)
        with patch("cli.telegram_bot.tg_send") as send:
            cmd_adaptlog("tok", "chat", "live")
            body = send.call_args[0][2]
            # Should show the live row only
            assert "LIVE" in body
    finally:
        p.stop()


def test_adaptlog_limit_respected(tmp_path):
    p = _patch_path(tmp_path)
    try:
        rows = [_row() for _ in range(30)]
        _write_rows(tmp_path, rows)
        with patch("cli.telegram_bot.tg_send") as send:
            cmd_adaptlog("tok", "chat", "5")
            body = send.call_args[0][2]
            assert "last 5 of 30" in body
    finally:
        p.stop()


# ---------------------------------------------------------------------------
# HANDLERS registration
# ---------------------------------------------------------------------------

def test_adaptlog_registered_in_handlers():
    from cli.telegram_bot import HANDLERS
    assert "/adaptlog" in HANDLERS
    assert "adaptlog" in HANDLERS


def test_adaptlog_in_help():
    from cli.telegram_bot import cmd_help
    with patch("cli.telegram_bot.tg_send") as send:
        cmd_help("tok", "chat", "")
        body = send.call_args[0][2]
        assert "/adaptlog" in body
