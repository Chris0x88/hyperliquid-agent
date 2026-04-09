"""Tests for /patterncatalog, /patternpromote, /patternreject (sub-system 6 L3)."""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from cli.telegram_commands.patternlib import (
    cmd_patterncatalog,
    cmd_patternpromote,
    cmd_patternreject,
)


def _patch_paths(tmp: Path):
    patchers = [
        patch(
            "cli.telegram_commands.patternlib.OIL_BOTPATTERN_PATTERN_CATALOG_JSON",
            str(tmp / "catalog.json"),
        ),
        patch(
            "cli.telegram_commands.patternlib.OIL_BOTPATTERN_PATTERN_CANDIDATES_JSONL",
            str(tmp / "candidates.jsonl"),
        ),
    ]
    for p in patchers:
        p.start()
    return patchers


def _stop(patchers):
    for p in patchers:
        p.stop()


# ---------------------------------------------------------------------------
# /patterncatalog
# ---------------------------------------------------------------------------

def test_patterncatalog_empty(tmp_path):
    patchers = _patch_paths(tmp_path)
    try:
        with patch("cli.telegram_bot.tg_send") as send:
            cmd_patterncatalog("tok", "chat", "")
            body = send.call_args[0][2]
            assert "Live catalog entries:* 0" in body
            assert "Pending candidates:* 0" in body
    finally:
        _stop(patchers)


def test_patterncatalog_shows_live_and_pending(tmp_path):
    patchers = _patch_paths(tmp_path)
    try:
        catalog = {
            "sig1": {
                "classification": "bot_driven_overextension",
                "direction": "down",
                "confidence_band": 0.70,
                "signals": ["overext", "oi_div"],
                "promoted_at": "2026-04-09T10:00:00+00:00",
            },
        }
        (tmp_path / "catalog.json").write_text(json.dumps(catalog))

        candidates = [
            {
                "id": 1, "status": "pending",
                "signature_key": "sig2",
                "classification": "informed_flow",
                "direction": "up",
                "confidence_band": 0.80,
                "signals": ["fresh_catalyst"],
                "occurrences": 4,
                "first_seen_at": "2026-04-05", "last_seen_at": "2026-04-08",
                "example_instruments": ["BRENTOIL"],
            },
            {
                "id": 2, "status": "promoted",
                "signature_key": "sig1",
                "classification": "bot_driven_overextension",
                "direction": "down", "confidence_band": 0.70,
                "signals": [], "occurrences": 5,
                "first_seen_at": "", "last_seen_at": "",
                "example_instruments": [],
            },
        ]
        (tmp_path / "candidates.jsonl").write_text(
            "\n".join(json.dumps(c) for c in candidates) + "\n"
        )

        with patch("cli.telegram_bot.tg_send") as send:
            cmd_patterncatalog("tok", "chat", "")
            body = send.call_args[0][2]
            assert "Live catalog entries:* 1" in body
            assert "Pending candidates:* 1" in body
            assert "Total candidates (all statuses):* 2" in body
            assert "bot_driven_overextension" in body
            assert "#1" in body
            assert "informed_flow" in body
    finally:
        _stop(patchers)


# ---------------------------------------------------------------------------
# /patternpromote
# ---------------------------------------------------------------------------

def test_patternpromote_success(tmp_path):
    patchers = _patch_paths(tmp_path)
    try:
        candidates = [{
            "id": 7, "status": "pending",
            "signature_key": "sig1",
            "classification": "test", "direction": "up",
            "confidence_band": 0.7, "signals": ["a"],
            "occurrences": 5,
            "first_seen_at": "2026-04-01", "last_seen_at": "2026-04-08",
            "example_instruments": ["BRENTOIL"],
        }]
        (tmp_path / "candidates.jsonl").write_text(
            "\n".join(json.dumps(c) for c in candidates) + "\n"
        )

        with patch("cli.telegram_bot.tg_send") as send:
            cmd_patternpromote("tok", "chat", "7")
            body = send.call_args[0][2]
            assert "promoted" in body.lower()

        # Catalog updated
        catalog = json.loads((tmp_path / "catalog.json").read_text())
        assert "sig1" in catalog
        assert catalog["sig1"]["classification"] == "test"

        # Candidate status updated
        candidates = [
            json.loads(line)
            for line in (tmp_path / "candidates.jsonl").read_text().splitlines()
            if line
        ]
        assert candidates[0]["status"] == "promoted"
    finally:
        _stop(patchers)


def test_patternpromote_missing_id(tmp_path):
    patchers = _patch_paths(tmp_path)
    try:
        with patch("cli.telegram_bot.tg_send") as send:
            cmd_patternpromote("tok", "chat", "")
            body = send.call_args[0][2]
            assert "Usage" in body
    finally:
        _stop(patchers)


def test_patternpromote_bad_id(tmp_path):
    patchers = _patch_paths(tmp_path)
    try:
        with patch("cli.telegram_bot.tg_send") as send:
            cmd_patternpromote("tok", "chat", "notanint")
            body = send.call_args[0][2]
            assert "Bad id" in body
    finally:
        _stop(patchers)


def test_patternpromote_not_found(tmp_path):
    patchers = _patch_paths(tmp_path)
    try:
        with patch("cli.telegram_bot.tg_send") as send:
            cmd_patternpromote("tok", "chat", "999")
            body = send.call_args[0][2]
            assert "not found" in body.lower()
    finally:
        _stop(patchers)


def test_patternpromote_non_pending(tmp_path):
    patchers = _patch_paths(tmp_path)
    try:
        candidates = [{
            "id": 1, "status": "rejected", "signature_key": "sig1",
        }]
        (tmp_path / "candidates.jsonl").write_text(
            json.dumps(candidates[0]) + "\n"
        )
        with patch("cli.telegram_bot.tg_send") as send:
            cmd_patternpromote("tok", "chat", "1")
            body = send.call_args[0][2]
            assert "not pending" in body.lower()
    finally:
        _stop(patchers)


# ---------------------------------------------------------------------------
# /patternreject
# ---------------------------------------------------------------------------

def test_patternreject_success(tmp_path):
    patchers = _patch_paths(tmp_path)
    try:
        candidates = [{
            "id": 5, "status": "pending", "signature_key": "sigx",
        }]
        (tmp_path / "candidates.jsonl").write_text(
            json.dumps(candidates[0]) + "\n"
        )
        with patch("cli.telegram_bot.tg_send") as send:
            cmd_patternreject("tok", "chat", "5")
            body = send.call_args[0][2]
            assert "rejected" in body.lower()

        # Catalog not created
        assert not (tmp_path / "catalog.json").exists()

        # Candidate status updated
        candidates = [
            json.loads(line)
            for line in (tmp_path / "candidates.jsonl").read_text().splitlines()
            if line
        ]
        assert candidates[0]["status"] == "rejected"
    finally:
        _stop(patchers)


def test_patternreject_missing_id(tmp_path):
    patchers = _patch_paths(tmp_path)
    try:
        with patch("cli.telegram_bot.tg_send") as send:
            cmd_patternreject("tok", "chat", "")
            body = send.call_args[0][2]
            assert "Usage" in body
    finally:
        _stop(patchers)


def test_patternreject_not_found(tmp_path):
    patchers = _patch_paths(tmp_path)
    try:
        with patch("cli.telegram_bot.tg_send") as send:
            cmd_patternreject("tok", "chat", "999")
            body = send.call_args[0][2]
            assert "not found" in body.lower()
    finally:
        _stop(patchers)


# ---------------------------------------------------------------------------
# 5-surface checklist sanity
# ---------------------------------------------------------------------------

def test_all_three_commands_registered_in_handlers():
    from cli.telegram_bot import HANDLERS
    for cmd in ("patterncatalog", "patternpromote", "patternreject"):
        assert f"/{cmd}" in HANDLERS, f"/{cmd} missing from HANDLERS"
        assert cmd in HANDLERS, f"bare {cmd} missing from HANDLERS"


def test_all_three_commands_in_help():
    from cli.telegram_bot import cmd_help
    with patch("cli.telegram_bot.tg_send") as send:
        cmd_help("tok", "chat", "")
        body = send.call_args[0][2]
        for cmd in ("/patterncatalog", "/patternpromote", "/patternreject"):
            assert cmd in body, f"{cmd} missing from /help"


def test_all_three_commands_in_guide():
    from cli.telegram_bot import cmd_guide
    with patch("cli.telegram_bot.tg_send") as send:
        cmd_guide("tok", "chat", "")
        body = send.call_args[0][2]
        for cmd in ("/patterncatalog", "/patternpromote", "/patternreject"):
            assert cmd in body, f"{cmd} missing from /guide"
