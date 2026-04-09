"""Tests for /selftune, /selftuneproposals, /selftuneapprove, /selftunereject."""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from cli.telegram_bot import (
    cmd_selftune,
    cmd_selftuneapprove,
    cmd_selftuneproposals,
    cmd_selftunereject,
)


def _patch_paths(tmp: Path):
    """Return a dict of patcher contexts for all 6 sub-system 6 paths."""
    patchers = []
    for name, fname in [
        ("OIL_BOTPATTERN_TUNE_CONFIG_JSON", "tune_cfg.json"),
        ("OIL_BOTPATTERN_REFLECT_CONFIG_JSON", "reflect_cfg.json"),
        ("OIL_BOTPATTERN_CONFIG_JSON", "oil_botpattern.json"),
        ("OIL_BOTPATTERN_REFLECT_STATE_JSON", "reflect_state.json"),
        ("OIL_BOTPATTERN_TUNE_AUDIT_JSONL", "tune_audit.jsonl"),
        ("OIL_BOTPATTERN_PROPOSALS_JSONL", "proposals.jsonl"),
    ]:
        patchers.append(patch(f"cli.telegram_bot.{name}", str(tmp / fname)))
    return patchers


def _apply_patches(patchers):
    for p in patchers:
        p.start()


def _stop_patches(patchers):
    for p in patchers:
        p.stop()


# ---------------------------------------------------------------------------
# /selftune
# ---------------------------------------------------------------------------

def test_selftune_reports_both_kill_switches_off(tmp_path):
    patchers = _patch_paths(tmp_path)
    _apply_patches(patchers)
    try:
        (tmp_path / "tune_cfg.json").write_text(json.dumps({
            "enabled": False,
            "bounds": {
                "long_min_edge": {"min": 0.35, "max": 0.70, "type": "float"},
            },
        }))
        (tmp_path / "reflect_cfg.json").write_text(json.dumps({"enabled": False}))
        (tmp_path / "oil_botpattern.json").write_text(json.dumps({"long_min_edge": 0.50}))

        with patch("cli.telegram_bot.tg_send") as send:
            cmd_selftune("tok", "chat", "")
            body = send.call_args[0][2]
            assert "L1 auto-tune" in body
            assert "L2 reflect" in body
            assert "🔴 OFF" in body
            assert "long_min_edge" in body
    finally:
        _stop_patches(patchers)


def test_selftune_shows_last_nudges(tmp_path):
    patchers = _patch_paths(tmp_path)
    _apply_patches(patchers)
    try:
        (tmp_path / "tune_cfg.json").write_text(json.dumps({
            "enabled": True,
            "bounds": {"long_min_edge": {"min": 0.35, "max": 0.70, "type": "float"}},
        }))
        (tmp_path / "reflect_cfg.json").write_text(json.dumps({"enabled": False}))
        (tmp_path / "oil_botpattern.json").write_text(json.dumps({"long_min_edge": 0.475}))

        audit_rows = [
            {"applied_at": "2026-04-08T10:00:00+00:00", "param": "long_min_edge",
             "old_value": 0.50, "new_value": 0.475, "source": "l1_auto_tune"},
        ]
        (tmp_path / "tune_audit.jsonl").write_text(
            "\n".join(json.dumps(r) for r in audit_rows)
        )

        with patch("cli.telegram_bot.tg_send") as send:
            cmd_selftune("tok", "chat", "")
            body = send.call_args[0][2]
            assert "0.5 → 0.475" in body or "0.50 → 0.475" in body
            assert "l1_auto_tune" in body
    finally:
        _stop_patches(patchers)


def test_selftune_shows_pending_proposal_count(tmp_path):
    patchers = _patch_paths(tmp_path)
    _apply_patches(patchers)
    try:
        (tmp_path / "tune_cfg.json").write_text(json.dumps({"enabled": False, "bounds": {}}))
        (tmp_path / "reflect_cfg.json").write_text(json.dumps({"enabled": False}))
        (tmp_path / "oil_botpattern.json").write_text(json.dumps({}))

        proposals = [
            {"id": 1, "type": "instrument_dead", "status": "pending",
             "description": "CL dead", "created_at": "2026-04-08T10:00:00+00:00",
             "proposed_action": {"kind": "advisory"}},
            {"id": 2, "type": "gate_overblock", "status": "approved",
             "description": "already done", "created_at": "2026-04-07T10:00:00+00:00",
             "proposed_action": {"kind": "advisory"}},
        ]
        (tmp_path / "proposals.jsonl").write_text(
            "\n".join(json.dumps(p) for p in proposals)
        )

        with patch("cli.telegram_bot.tg_send") as send:
            cmd_selftune("tok", "chat", "")
            body = send.call_args[0][2]
            assert "Pending proposals" in body
            assert "1" in body  # 1 pending, 2 total
    finally:
        _stop_patches(patchers)


# ---------------------------------------------------------------------------
# /selftuneproposals
# ---------------------------------------------------------------------------

def test_selftuneproposals_empty(tmp_path):
    patchers = _patch_paths(tmp_path)
    _apply_patches(patchers)
    try:
        with patch("cli.telegram_bot.tg_send") as send:
            cmd_selftuneproposals("tok", "chat", "")
            body = send.call_args[0][2]
            assert "No pending self-tune proposals" in body
    finally:
        _stop_patches(patchers)


def test_selftuneproposals_lists_pending_only(tmp_path):
    patchers = _patch_paths(tmp_path)
    _apply_patches(patchers)
    try:
        proposals = [
            {"id": 1, "type": "instrument_dead", "status": "pending",
             "description": "CL is dead", "created_at": "2026-04-08T10:00:00+00:00",
             "proposed_action": {"kind": "advisory",
                                 "target": "data/config/oil_botpattern.json",
                                 "path": "instruments", "notes": "remove CL"}},
            {"id": 2, "type": "gate_overblock", "status": "approved",
             "description": "already done", "created_at": "2026-04-07T10:00:00+00:00",
             "proposed_action": {"kind": "advisory"}},
            {"id": 3, "type": "funding_exit_expensive", "status": "rejected",
             "description": "dismissed", "created_at": "2026-04-06T10:00:00+00:00",
             "proposed_action": {"kind": "advisory"}},
        ]
        (tmp_path / "proposals.jsonl").write_text(
            "\n".join(json.dumps(p) for p in proposals)
        )
        with patch("cli.telegram_bot.tg_send") as send:
            cmd_selftuneproposals("tok", "chat", "")
            body = send.call_args[0][2]
            assert "#1" in body
            assert "CL is dead" in body
            assert "#2" not in body  # approved, not pending
            assert "#3" not in body  # rejected, not pending
    finally:
        _stop_patches(patchers)


# ---------------------------------------------------------------------------
# /selftuneapprove
# ---------------------------------------------------------------------------

def test_selftuneapprove_config_change_applies(tmp_path):
    patchers = _patch_paths(tmp_path)
    _apply_patches(patchers)
    try:
        strat_cfg_path = tmp_path / "oil_botpattern.json"
        strat_cfg_path.write_text(json.dumps({"short_blocking_catalyst_severity": 4}))

        proposals = [{
            "id": 42, "type": "gate_overblock", "status": "pending",
            "description": "raise sev floor",
            "created_at": "2026-04-08T10:00:00+00:00",
            "evidence": {"hits": 8},
            "proposed_action": {
                "kind": "config_change",
                "target": str(strat_cfg_path),
                "path": "short_blocking_catalyst_severity",
                "old_value": 4, "new_value": 5,
            },
        }]
        (tmp_path / "proposals.jsonl").write_text(
            "\n".join(json.dumps(p) for p in proposals)
        )

        with patch("cli.telegram_bot.tg_send") as send:
            cmd_selftuneapprove("tok", "chat", "42")
            body = send.call_args[0][2]
            assert "approved" in body.lower()
            assert "42" in body

        # Config mutated
        new_cfg = json.loads(strat_cfg_path.read_text())
        assert new_cfg["short_blocking_catalyst_severity"] == 5

        # Proposal status updated
        proposals = [
            json.loads(l) for l in (tmp_path / "proposals.jsonl").read_text().splitlines() if l
        ]
        assert proposals[0]["status"] == "approved"
        assert proposals[0]["reviewed_outcome"] == "applied"

        # Audit log has a reflect_approved record
        audit_lines = (tmp_path / "tune_audit.jsonl").read_text().splitlines()
        assert len(audit_lines) == 1
        audit = json.loads(audit_lines[0])
        assert audit["source"] == "reflect_approved"
        assert audit["param"] == "short_blocking_catalyst_severity"
    finally:
        _stop_patches(patchers)


def test_selftuneapprove_advisory_is_no_op_file_change(tmp_path):
    patchers = _patch_paths(tmp_path)
    _apply_patches(patchers)
    try:
        proposals = [{
            "id": 7, "type": "instrument_dead", "status": "pending",
            "description": "CL dead", "created_at": "2026-04-08T10:00:00+00:00",
            "proposed_action": {"kind": "advisory", "notes": "manual review"},
        }]
        (tmp_path / "proposals.jsonl").write_text(
            "\n".join(json.dumps(p) for p in proposals)
        )
        with patch("cli.telegram_bot.tg_send") as send:
            cmd_selftuneapprove("tok", "chat", "7")
            body = send.call_args[0][2]
            assert "approved" in body.lower()

        proposals = [
            json.loads(l) for l in (tmp_path / "proposals.jsonl").read_text().splitlines() if l
        ]
        assert proposals[0]["status"] == "approved"
    finally:
        _stop_patches(patchers)


def test_selftuneapprove_not_found(tmp_path):
    patchers = _patch_paths(tmp_path)
    _apply_patches(patchers)
    try:
        with patch("cli.telegram_bot.tg_send") as send:
            cmd_selftuneapprove("tok", "chat", "999")
            body = send.call_args[0][2]
            assert "not found" in body.lower()
    finally:
        _stop_patches(patchers)


def test_selftuneapprove_rejects_non_pending(tmp_path):
    patchers = _patch_paths(tmp_path)
    _apply_patches(patchers)
    try:
        proposals = [{
            "id": 1, "type": "instrument_dead", "status": "rejected",
            "description": "x", "created_at": "2026-04-01T00:00:00+00:00",
            "proposed_action": {"kind": "advisory"},
        }]
        (tmp_path / "proposals.jsonl").write_text(
            "\n".join(json.dumps(p) for p in proposals)
        )
        with patch("cli.telegram_bot.tg_send") as send:
            cmd_selftuneapprove("tok", "chat", "1")
            body = send.call_args[0][2]
            assert "not pending" in body.lower()
    finally:
        _stop_patches(patchers)


def test_selftuneapprove_bad_id(tmp_path):
    patchers = _patch_paths(tmp_path)
    _apply_patches(patchers)
    try:
        with patch("cli.telegram_bot.tg_send") as send:
            cmd_selftuneapprove("tok", "chat", "nope")
            body = send.call_args[0][2]
            assert "Bad id" in body
    finally:
        _stop_patches(patchers)


def test_selftuneapprove_missing_id(tmp_path):
    patchers = _patch_paths(tmp_path)
    _apply_patches(patchers)
    try:
        with patch("cli.telegram_bot.tg_send") as send:
            cmd_selftuneapprove("tok", "chat", "")
            body = send.call_args[0][2]
            assert "Usage" in body
    finally:
        _stop_patches(patchers)


# ---------------------------------------------------------------------------
# /selftunereject
# ---------------------------------------------------------------------------

def test_selftunereject_marks_rejected(tmp_path):
    patchers = _patch_paths(tmp_path)
    _apply_patches(patchers)
    try:
        proposals = [{
            "id": 5, "type": "instrument_dead", "status": "pending",
            "description": "CL dead", "created_at": "2026-04-08T10:00:00+00:00",
            "proposed_action": {"kind": "advisory"},
        }]
        (tmp_path / "proposals.jsonl").write_text(
            "\n".join(json.dumps(p) for p in proposals)
        )
        with patch("cli.telegram_bot.tg_send") as send:
            cmd_selftunereject("tok", "chat", "5")
            body = send.call_args[0][2]
            assert "rejected" in body.lower()
            assert "5" in body

        proposals = [
            json.loads(l) for l in (tmp_path / "proposals.jsonl").read_text().splitlines() if l
        ]
        assert proposals[0]["status"] == "rejected"
        assert proposals[0]["reviewed_outcome"] == "rejected"
    finally:
        _stop_patches(patchers)


def test_selftunereject_does_not_touch_target_file(tmp_path):
    patchers = _patch_paths(tmp_path)
    _apply_patches(patchers)
    try:
        strat_cfg_path = tmp_path / "oil_botpattern.json"
        strat_cfg_path.write_text(json.dumps({"short_blocking_catalyst_severity": 4}))

        proposals = [{
            "id": 5, "type": "gate_overblock", "status": "pending",
            "description": "raise",
            "created_at": "2026-04-08T10:00:00+00:00",
            "proposed_action": {
                "kind": "config_change",
                "target": str(strat_cfg_path),
                "path": "short_blocking_catalyst_severity",
                "old_value": 4, "new_value": 5,
            },
        }]
        (tmp_path / "proposals.jsonl").write_text(
            "\n".join(json.dumps(p) for p in proposals)
        )
        with patch("cli.telegram_bot.tg_send"):
            cmd_selftunereject("tok", "chat", "5")

        # Target file MUST be unchanged
        assert json.loads(strat_cfg_path.read_text())["short_blocking_catalyst_severity"] == 4
        # Audit log must NOT have a new row
        assert not (tmp_path / "tune_audit.jsonl").exists() or \
               (tmp_path / "tune_audit.jsonl").read_text() == ""
    finally:
        _stop_patches(patchers)


# ---------------------------------------------------------------------------
# 5-surface checklist sanity — command is reachable via HANDLERS
# ---------------------------------------------------------------------------

def test_all_four_commands_registered_in_handlers():
    from cli.telegram_bot import HANDLERS
    for cmd in ("selftune", "selftuneproposals", "selftuneapprove", "selftunereject"):
        assert f"/{cmd}" in HANDLERS, f"/{cmd} missing from HANDLERS"
        assert cmd in HANDLERS, f"bare {cmd} missing from HANDLERS"


def test_all_four_commands_in_help():
    from cli.telegram_bot import cmd_help
    with patch("cli.telegram_bot.tg_send") as send:
        cmd_help("tok", "chat", "")
        body = send.call_args[0][2]
        for cmd in ("/selftune", "/selftuneproposals", "/selftuneapprove", "/selftunereject"):
            assert cmd in body, f"{cmd} missing from /help"


def test_all_four_commands_in_guide():
    from cli.telegram_bot import cmd_guide
    with patch("cli.telegram_bot.tg_send") as send:
        cmd_guide("tok", "chat", "")
        body = send.call_args[0][2]
        for cmd in ("/selftune", "/selftuneproposals", "/selftuneapprove", "/selftunereject"):
            assert cmd in body, f"{cmd} missing from /guide"
