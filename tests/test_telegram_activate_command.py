"""Tests for /activate — guided sub-system 5 activation walkthrough."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from cli.telegram_commands.activate import (
    apply_patch_to_config,
    can_advance,
    classify_rung,
    cmd_activate,
    next_rung_action,
    rollback_action,
)


UTC = timezone.utc


def _patch_paths(tmp: Path):
    patchers = [
        patch("cli.telegram_commands.activate.OIL_BOTPATTERN_CONFIG_JSON",
              str(tmp / "oil_botpattern.json")),
        patch("cli.telegram_commands.activate.ACTIVATION_LOG_JSONL",
              str(tmp / "activation_log.jsonl")),
        patch("cli.telegram_commands.activate.PENDING_ADVANCE_JSON",
              str(tmp / "pending_advance.json")),
    ]
    for p in patchers:
        p.start()
    return patchers


def _stop(patchers):
    for p in patchers:
        p.stop()


def _write_cfg(tmp: Path, **fields):
    base = {
        "enabled": False,
        "decisions_only": False,
        "short_legs_enabled": False,
    }
    base.update(fields)
    (tmp / "oil_botpattern.json").write_text(json.dumps(base, indent=2))


def _patch_readiness(verdict: str = "🟢 *GO* — all preflight checks green"):
    """Stub compute_readiness so /activate tests don't depend on real files."""
    return patch(
        "cli.telegram_commands.readiness.compute_readiness",
        return_value=([("🟢", "stub", "ok", "green")], verdict),
    )


# ---------------------------------------------------------------------------
# classify_rung
# ---------------------------------------------------------------------------

def test_classify_rung_0_disabled():
    r, label = classify_rung({"enabled": False})
    assert r == 0
    assert "DISABLED" in label


def test_classify_rung_1_shadow():
    r, label = classify_rung({"enabled": True, "decisions_only": True})
    assert r == 1
    assert "SHADOW" in label


def test_classify_rung_3_live_longs_only():
    r, label = classify_rung({"enabled": True, "decisions_only": False, "short_legs_enabled": False})
    assert r == 3
    assert "LIVE longs only" in label


def test_classify_rung_4_live_plus_shorts():
    r, label = classify_rung({"enabled": True, "decisions_only": False, "short_legs_enabled": True})
    assert r == 4
    assert "longs + shorts" in label


# ---------------------------------------------------------------------------
# next_rung_action
# ---------------------------------------------------------------------------

def test_next_from_0_promotes_to_shadow():
    target, desc, patch_dict = next_rung_action(0)
    assert target == 1
    assert patch_dict["enabled"] is True
    assert patch_dict["decisions_only"] is True
    assert patch_dict["short_legs_enabled"] is False


def test_next_from_1_promotes_to_live_longs():
    target, _desc, patch_dict = next_rung_action(1)
    assert target == 3
    assert patch_dict["decisions_only"] is False


def test_next_from_3_enables_shorts():
    target, _desc, patch_dict = next_rung_action(3)
    assert target == 4
    assert patch_dict["short_legs_enabled"] is True


def test_next_from_4_noop():
    target, _desc, patch_dict = next_rung_action(4)
    assert target == 4
    assert patch_dict == {}


# ---------------------------------------------------------------------------
# rollback_action
# ---------------------------------------------------------------------------

def test_rollback_from_4_disables_shorts():
    target, _desc, patch_dict = rollback_action(4)
    assert target == 3
    assert patch_dict["short_legs_enabled"] is False


def test_rollback_from_3_to_shadow():
    target, _desc, patch_dict = rollback_action(3)
    assert target == 1
    assert patch_dict["decisions_only"] is True


def test_rollback_from_1_to_disabled():
    target, _desc, patch_dict = rollback_action(1)
    assert target == 0
    assert patch_dict["enabled"] is False


def test_rollback_from_0_noop():
    target, _desc, patch_dict = rollback_action(0)
    assert target == 0
    assert patch_dict == {}


# ---------------------------------------------------------------------------
# can_advance gating
# ---------------------------------------------------------------------------

def test_can_advance_to_shadow_always_allowed_even_on_red():
    with _patch_readiness(verdict="🔴 *DO NOT ACTIVATE*"):
        ok, _msg = can_advance(0, 1)
        assert ok is True


def test_can_advance_to_live_blocked_on_red():
    with _patch_readiness(verdict="🔴 *DO NOT ACTIVATE*"):
        ok, msg = can_advance(1, 3)
        assert ok is False
        assert "Cannot promote" in msg


def test_can_advance_to_live_allowed_on_yellow():
    with _patch_readiness(verdict="🟡 *PROCEED WITH CAUTION*"):
        ok, msg = can_advance(1, 3)
        assert ok is True
        assert "Yellow" in msg


def test_can_advance_to_shorts_requires_green():
    with _patch_readiness(verdict="🟡 *PROCEED WITH CAUTION*"):
        ok, _msg = can_advance(3, 4)
        assert ok is False


def test_can_advance_to_shorts_allowed_on_green():
    with _patch_readiness(verdict="🟢 *GO*"):
        ok, _msg = can_advance(3, 4)
        assert ok is True


# ---------------------------------------------------------------------------
# apply_patch_to_config
# ---------------------------------------------------------------------------

def test_apply_patch_merges_fields(tmp_path):
    patchers = _patch_paths(tmp_path)
    try:
        _write_cfg(tmp_path, enabled=False)
        new_cfg = apply_patch_to_config(
            str(tmp_path / "oil_botpattern.json"),
            {"enabled": True, "decisions_only": True},
        )
        assert new_cfg["enabled"] is True
        assert new_cfg["decisions_only"] is True
        on_disk = json.loads((tmp_path / "oil_botpattern.json").read_text())
        assert on_disk == new_cfg
    finally:
        _stop(patchers)


# ---------------------------------------------------------------------------
# /activate end-to-end
# ---------------------------------------------------------------------------

def test_activate_status_shows_current_rung(tmp_path):
    patchers = _patch_paths(tmp_path)
    try:
        _write_cfg(tmp_path, enabled=False)
        with _patch_readiness(), patch("cli.telegram_bot.tg_send") as send:
            cmd_activate("tok", "chat", "")
            body = send.call_args[0][2]
            assert "Rung 0" in body
            assert "DISABLED" in body
            assert "Next step" in body
    finally:
        _stop(patchers)


def test_activate_next_stages_pending(tmp_path):
    patchers = _patch_paths(tmp_path)
    try:
        _write_cfg(tmp_path, enabled=False)
        with _patch_readiness(), patch("cli.telegram_bot.tg_send") as send:
            cmd_activate("tok", "chat", "next")
            body = send.call_args[0][2]
            assert "Pending advance" in body
            assert "Rung 0 → Rung 1" in body
            # Pending file written
            pending = json.loads((tmp_path / "pending_advance.json").read_text())
            assert pending["to_rung"] == 1
            assert pending["patch"]["decisions_only"] is True
    finally:
        _stop(patchers)


def test_activate_confirm_applies_patch(tmp_path):
    patchers = _patch_paths(tmp_path)
    try:
        _write_cfg(tmp_path, enabled=False)
        with _patch_readiness(), patch("cli.telegram_bot.tg_send") as send:
            cmd_activate("tok", "chat", "next")
            cmd_activate("tok", "chat", "confirm")
            last_call = send.call_args_list[-1]
            body = last_call[0][2]
            assert "Advanced to Rung 1" in body

        # Config file actually updated
        cfg = json.loads((tmp_path / "oil_botpattern.json").read_text())
        assert cfg["enabled"] is True
        assert cfg["decisions_only"] is True

        # Activation log written
        log_lines = (tmp_path / "activation_log.jsonl").read_text().splitlines()
        assert len(log_lines) == 1
        record = json.loads(log_lines[0])
        assert record["kind"] == "advance"
        assert record["from_rung"] == 0
        assert record["to_rung"] == 1

        # Pending file cleared
        assert not (tmp_path / "pending_advance.json").exists()
    finally:
        _stop(patchers)


def test_activate_confirm_without_pending(tmp_path):
    patchers = _patch_paths(tmp_path)
    try:
        _write_cfg(tmp_path, enabled=False)
        with _patch_readiness(), patch("cli.telegram_bot.tg_send") as send:
            cmd_activate("tok", "chat", "confirm")
            body = send.call_args[0][2]
            assert "No pending advance" in body
    finally:
        _stop(patchers)


def test_activate_confirm_stale_pending(tmp_path):
    patchers = _patch_paths(tmp_path)
    try:
        _write_cfg(tmp_path, enabled=False)
        stale_pending = {
            "staged_at": (datetime.now(tz=UTC) - timedelta(minutes=30)).isoformat(),
            "from_rung": 0, "to_rung": 1,
            "patch": {"enabled": True, "decisions_only": True},
        }
        (tmp_path / "pending_advance.json").write_text(json.dumps(stale_pending))
        with _patch_readiness(), patch("cli.telegram_bot.tg_send") as send:
            cmd_activate("tok", "chat", "confirm")
            body = send.call_args[0][2]
            assert "stale" in body.lower()
        # Config unchanged
        cfg = json.loads((tmp_path / "oil_botpattern.json").read_text())
        assert cfg["enabled"] is False
    finally:
        _stop(patchers)


def test_activate_next_blocked_by_red_gate_for_live(tmp_path):
    patchers = _patch_paths(tmp_path)
    try:
        _write_cfg(tmp_path, enabled=True, decisions_only=True)
        with _patch_readiness(verdict="🔴 *DO NOT ACTIVATE*"), patch("cli.telegram_bot.tg_send") as send:
            cmd_activate("tok", "chat", "next")
            body = send.call_args[0][2]
            assert "Cannot advance" in body
        # No pending file written
        assert not (tmp_path / "pending_advance.json").exists()
    finally:
        _stop(patchers)


def test_activate_back_rolls_back_one_rung(tmp_path):
    patchers = _patch_paths(tmp_path)
    try:
        _write_cfg(tmp_path, enabled=True, decisions_only=True)  # rung 1
        with _patch_readiness(), patch("cli.telegram_bot.tg_send") as send:
            cmd_activate("tok", "chat", "back")
            body = send.call_args[0][2]
            assert "Rolled back to Rung 0" in body
        cfg = json.loads((tmp_path / "oil_botpattern.json").read_text())
        assert cfg["enabled"] is False

        # Activation log recorded the rollback
        log_lines = (tmp_path / "activation_log.jsonl").read_text().splitlines()
        record = json.loads(log_lines[-1])
        assert record["kind"] == "soft_rollback"
        assert record["from_rung"] == 1
        assert record["to_rung"] == 0
    finally:
        _stop(patchers)


def test_activate_hard_rollback_force_disables(tmp_path):
    patchers = _patch_paths(tmp_path)
    try:
        _write_cfg(tmp_path, enabled=True, decisions_only=False, short_legs_enabled=True)  # rung 4
        with _patch_readiness(), patch("cli.telegram_bot.tg_send") as send:
            cmd_activate("tok", "chat", "rollback")
            body = send.call_args[0][2]
            assert "HARD ROLLBACK" in body
        cfg = json.loads((tmp_path / "oil_botpattern.json").read_text())
        assert cfg["enabled"] is False
    finally:
        _stop(patchers)


def test_activate_next_replaces_previous_pending(tmp_path):
    patchers = _patch_paths(tmp_path)
    try:
        _write_cfg(tmp_path, enabled=False)
        with _patch_readiness(), patch("cli.telegram_bot.tg_send"):
            cmd_activate("tok", "chat", "next")
            first = json.loads((tmp_path / "pending_advance.json").read_text())
            cmd_activate("tok", "chat", "next")
            second = json.loads((tmp_path / "pending_advance.json").read_text())
            # Both describe same advance (rung 0 → 1) but timestamps differ
            assert first["to_rung"] == second["to_rung"] == 1
    finally:
        _stop(patchers)


# ---------------------------------------------------------------------------
# HANDLERS registration
# ---------------------------------------------------------------------------

def test_activate_registered_in_handlers():
    from cli.telegram_bot import HANDLERS
    assert "/activate" in HANDLERS
    assert "activate" in HANDLERS


def test_activate_in_help():
    from cli.telegram_bot import cmd_help
    with patch("cli.telegram_bot.tg_send") as send:
        cmd_help("tok", "chat", "")
        body = send.call_args[0][2]
        assert "/activate" in body
