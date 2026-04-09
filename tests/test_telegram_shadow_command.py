"""Tests for /shadoweval (sub-system 6 L4)."""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from cli.telegram_commands.shadow import cmd_shadoweval


def _patch_paths(tmp: Path):
    patchers = [
        patch(
            "cli.telegram_commands.shadow.OIL_BOTPATTERN_SHADOW_EVALS_JSONL",
            str(tmp / "shadow_evals.jsonl"),
        ),
        patch(
            "cli.telegram_commands.shadow.OIL_BOTPATTERN_PROPOSALS_JSONL",
            str(tmp / "proposals.jsonl"),
        ),
    ]
    for p in patchers:
        p.start()
    return patchers


def _stop(patchers):
    for p in patchers:
        p.stop()


def _eval_row(pid: int = 42) -> dict:
    return {
        "proposal_id": pid, "proposal_type": "gate_overblock",
        "evaluated_at": "2026-04-09T10:00:00+00:00",
        "window_days": 30,
        "trades_in_window": 5,
        "decisions_in_window": 20,
        "param": "long_min_edge",
        "current_value": 0.50,
        "proposed_value": 0.45,
        "would_have_entered_same": 18,
        "would_have_diverged": 2,
        "divergence_rate": 0.10,
        "sample_sufficient": True,
        "counterfactual_pnl_estimate_usd": 123.45,
        "notes": "Edge-threshold replay: 2 newly entered, 0 newly skipped, 18 unchanged.",
    }


# ---------------------------------------------------------------------------
# Summary mode (no arg)
# ---------------------------------------------------------------------------

def test_shadoweval_empty_summary(tmp_path):
    patchers = _patch_paths(tmp_path)
    try:
        with patch("cli.telegram_bot.tg_send") as send:
            cmd_shadoweval("tok", "chat", "")
            body = send.call_args[0][2]
            assert "No shadow evaluations" in body
    finally:
        _stop(patchers)


def test_shadoweval_summary_lists_evals(tmp_path):
    patchers = _patch_paths(tmp_path)
    try:
        (tmp_path / "shadow_evals.jsonl").write_text(
            json.dumps(_eval_row(1)) + "\n"
            + json.dumps(_eval_row(2)) + "\n"
        )
        with patch("cli.telegram_bot.tg_send") as send:
            cmd_shadoweval("tok", "chat", "")
            body = send.call_args[0][2]
            assert "Shadow evaluations" in body
            assert "#1" in body
            assert "#2" in body
            assert "long_min_edge" in body
    finally:
        _stop(patchers)


# ---------------------------------------------------------------------------
# Detail mode (with id)
# ---------------------------------------------------------------------------

def test_shadoweval_detail_for_existing(tmp_path):
    patchers = _patch_paths(tmp_path)
    try:
        (tmp_path / "shadow_evals.jsonl").write_text(
            json.dumps(_eval_row(42)) + "\n"
        )
        (tmp_path / "proposals.jsonl").write_text(
            json.dumps({
                "id": 42, "type": "gate_overblock",
                "description": "raise long_min_edge",
                "status": "approved",
            }) + "\n"
        )
        with patch("cli.telegram_bot.tg_send") as send:
            cmd_shadoweval("tok", "chat", "42")
            body = send.call_args[0][2]
            assert "Shadow eval #42" in body
            assert "long_min_edge" in body
            assert "raise long_min_edge" in body
            assert "diverged outcomes: 2" in body
            assert "Sample sufficient" in body
    finally:
        _stop(patchers)


def test_shadoweval_detail_not_found(tmp_path):
    patchers = _patch_paths(tmp_path)
    try:
        with patch("cli.telegram_bot.tg_send") as send:
            cmd_shadoweval("tok", "chat", "999")
            body = send.call_args[0][2]
            assert "No shadow evaluation found" in body
    finally:
        _stop(patchers)


def test_shadoweval_bad_id(tmp_path):
    patchers = _patch_paths(tmp_path)
    try:
        with patch("cli.telegram_bot.tg_send") as send:
            cmd_shadoweval("tok", "chat", "nope")
            body = send.call_args[0][2]
            assert "Bad id" in body
    finally:
        _stop(patchers)


def test_shadoweval_insufficient_sample_flag(tmp_path):
    patchers = _patch_paths(tmp_path)
    try:
        row = _eval_row(7)
        row["sample_sufficient"] = False
        (tmp_path / "shadow_evals.jsonl").write_text(json.dumps(row) + "\n")
        with patch("cli.telegram_bot.tg_send") as send:
            cmd_shadoweval("tok", "chat", "7")
            body = send.call_args[0][2]
            assert "insufficient" in body.lower()
    finally:
        _stop(patchers)


# ---------------------------------------------------------------------------
# 5-surface checklist
# ---------------------------------------------------------------------------

def test_shadoweval_registered_in_handlers():
    from cli.telegram_bot import HANDLERS
    assert "/shadoweval" in HANDLERS
    assert "shadoweval" in HANDLERS


def test_shadoweval_in_help():
    from cli.telegram_bot import cmd_help
    with patch("cli.telegram_bot.tg_send") as send:
        cmd_help("tok", "chat", "")
        body = send.call_args[0][2]
        assert "/shadoweval" in body


def test_shadoweval_in_guide():
    from cli.telegram_bot import cmd_guide
    with patch("cli.telegram_bot.tg_send") as send:
        cmd_guide("tok", "chat", "")
        body = send.call_args[0][2]
        assert "/shadoweval" in body
