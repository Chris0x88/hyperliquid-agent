"""Tests for /sim — shadow (paper) account state command."""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from telegram.commands.sim import cmd_sim


def _patch_paths(tmp: Path):
    patchers = [
        patch("telegram.commands.sim.SHADOW_POSITIONS_JSON", str(tmp / "shadow_positions.json")),
        patch("telegram.commands.sim.SHADOW_TRADES_JSONL", str(tmp / "shadow_trades.jsonl")),
        patch("telegram.commands.sim.SHADOW_BALANCE_JSON", str(tmp / "shadow_balance.json")),
        patch("telegram.commands.sim.OIL_BOTPATTERN_CONFIG_JSON", str(tmp / "oil_botpattern.json")),
    ]
    for p in patchers:
        p.start()
    return patchers


def _stop(patchers):
    for p in patchers:
        p.stop()


def _write_config(tmp: Path, **overrides):
    cfg = {
        "enabled": True,
        "decisions_only": True,
        "shadow_seed_balance_usd": 100_000.0,
        "shadow_sl_pct": 2.0,
        "shadow_tp_pct": 5.0,
    }
    cfg.update(overrides)
    (tmp / "oil_botpattern.json").write_text(json.dumps(cfg))


# ---------------------------------------------------------------------------
# Mode reporting
# ---------------------------------------------------------------------------

def test_sim_reports_disabled_mode(tmp_path):
    patchers = _patch_paths(tmp_path)
    try:
        _write_config(tmp_path, enabled=False, decisions_only=False)
        with patch("telegram.bot.tg_send") as send:
            cmd_sim("tok", "chat", "")
            body = send.call_args[0][2]
            assert "DISABLED" in body
            assert "$100,000" in body  # seed balance default
    finally:
        _stop(patchers)


def test_sim_reports_shadow_mode(tmp_path):
    patchers = _patch_paths(tmp_path)
    try:
        _write_config(tmp_path, enabled=True, decisions_only=True)
        with patch("telegram.bot.tg_send") as send:
            cmd_sim("tok", "chat", "")
            body = send.call_args[0][2]
            assert "SHADOW" in body
            assert "decisions_only=true" in body
    finally:
        _stop(patchers)


def test_sim_reports_live_mode(tmp_path):
    patchers = _patch_paths(tmp_path)
    try:
        _write_config(tmp_path, enabled=True, decisions_only=False)
        with patch("telegram.bot.tg_send") as send:
            cmd_sim("tok", "chat", "")
            body = send.call_args[0][2]
            assert "LIVE" in body
            assert "real orders" in body
    finally:
        _stop(patchers)


# ---------------------------------------------------------------------------
# Balance rendering
# ---------------------------------------------------------------------------

def test_sim_renders_balance_with_pnl(tmp_path):
    patchers = _patch_paths(tmp_path)
    try:
        _write_config(tmp_path)
        (tmp_path / "shadow_balance.json").write_text(json.dumps({
            "seed_balance_usd": 100_000.0,
            "current_balance_usd": 103_450.0,
            "realised_pnl_usd": 3_450.0,
            "closed_trades": 8,
            "wins": 5,
            "losses": 3,
            "last_updated_at": "2026-04-09T10:00:00+00:00",
        }))
        with patch("telegram.bot.tg_send") as send:
            cmd_sim("tok", "chat", "")
            body = send.call_args[0][2]
            assert "$103,450" in body
            assert "+3.45" in body  # pnl %
            assert "8 closed" in body
            assert "5W / 3L" in body
            assert "WR 62%" in body
    finally:
        _stop(patchers)


def test_sim_seed_when_no_balance_file(tmp_path):
    patchers = _patch_paths(tmp_path)
    try:
        _write_config(tmp_path, shadow_seed_balance_usd=50_000.0)
        with patch("telegram.bot.tg_send") as send:
            cmd_sim("tok", "chat", "")
            body = send.call_args[0][2]
            assert "$50,000" in body
            assert "0 closed" in body
    finally:
        _stop(patchers)


# ---------------------------------------------------------------------------
# Open positions
# ---------------------------------------------------------------------------

def test_sim_renders_open_positions(tmp_path):
    patchers = _patch_paths(tmp_path)
    try:
        _write_config(tmp_path)
        (tmp_path / "shadow_positions.json").write_text(json.dumps({
            "positions": [
                {
                    "instrument": "BRENTOIL",
                    "side": "long",
                    "entry_ts": "2026-04-09T09:00:00+00:00",
                    "entry_price": 67.42,
                    "size": 1000.0,
                    "leverage": 5.0,
                    "notional_usd": 67420.0,
                    "stop_price": 66.07,
                    "tp_price": 70.79,
                    "edge": 0.72,
                    "rung": 2,
                    "unrealized_pnl_usd": 580.0,
                    "last_mark_ts": "2026-04-09T10:00:00+00:00",
                    "last_mark_price": 68.0,
                },
            ],
        }))
        with patch("telegram.bot.tg_send") as send:
            cmd_sim("tok", "chat", "")
            body = send.call_args[0][2]
            assert "Open shadow positions" in body
            assert "LONG BRENTOIL" in body
            assert "67.42" in body
            assert "mark 68.00" in body
            assert "edge=0.72" in body
    finally:
        _stop(patchers)


def test_sim_no_positions_message(tmp_path):
    patchers = _patch_paths(tmp_path)
    try:
        _write_config(tmp_path)
        with patch("telegram.bot.tg_send") as send:
            cmd_sim("tok", "chat", "")
            body = send.call_args[0][2]
            assert "Open shadow positions:* none" in body
    finally:
        _stop(patchers)


# ---------------------------------------------------------------------------
# Recent trades
# ---------------------------------------------------------------------------

def test_sim_renders_recent_trades(tmp_path):
    patchers = _patch_paths(tmp_path)
    try:
        _write_config(tmp_path)
        trades = [
            {
                "instrument": "BRENTOIL", "side": "long",
                "entry_ts": "2026-04-08T10:00:00+00:00", "exit_ts": "2026-04-08T13:00:00+00:00",
                "entry_price": 67.0, "exit_price": 70.35,
                "size": 1000, "leverage": 5, "notional_usd": 67000,
                "exit_reason": "tp_hit", "realised_pnl_usd": 3350, "roe_pct": 25.0,
                "edge": 0.72, "rung": 2, "hold_hours": 3.0,
            },
            {
                "instrument": "BRENTOIL", "side": "long",
                "entry_ts": "2026-04-09T05:00:00+00:00", "exit_ts": "2026-04-09T06:00:00+00:00",
                "entry_price": 68.0, "exit_price": 66.64,
                "size": 1000, "leverage": 5, "notional_usd": 68000,
                "exit_reason": "sl_hit", "realised_pnl_usd": -1360, "roe_pct": -10.0,
                "edge": 0.72, "rung": 2, "hold_hours": 1.0,
            },
        ]
        (tmp_path / "shadow_trades.jsonl").write_text(
            "".join(json.dumps(t) + "\n" for t in trades)
        )
        with patch("telegram.bot.tg_send") as send:
            cmd_sim("tok", "chat", "")
            body = send.call_args[0][2]
            assert "Recent closed trades" in body
            assert "🟢" in body  # winning trade
            assert "🔴" in body  # losing trade
            assert "tp_hit" in body
            assert "sl_hit" in body
    finally:
        _stop(patchers)


# ---------------------------------------------------------------------------
# HANDLERS registration
# ---------------------------------------------------------------------------

def test_sim_registered_in_handlers():
    from telegram.bot import HANDLERS
    assert "/sim" in HANDLERS
    assert "sim" in HANDLERS


def test_sim_in_help():
    from telegram.bot import cmd_help
    with patch("telegram.bot.tg_send") as send:
        cmd_help("tok", "chat", "")
        body = send.call_args[0][2]
        assert "/sim" in body
