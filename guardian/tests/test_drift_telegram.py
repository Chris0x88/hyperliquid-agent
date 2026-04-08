"""Tests for drift.detect_telegram_gaps()."""
from __future__ import annotations

from guardian.drift import detect_telegram_gaps


def test_no_gaps_when_fully_registered():
    telegram = {
        "handlers": [{"name": "cmd_hello"}, {"name": "cmd_bye"}],
        "handlers_dict_keys": ["/hello", "hello", "/bye", "bye"],
        "menu_commands": ["hello", "bye"],
        "help_mentions": ["/hello", "/bye"],
        "guide_mentions": ["/hello", "/bye"],
    }
    gaps = detect_telegram_gaps(telegram)
    assert gaps == []


def test_detects_unregistered_handler():
    telegram = {
        "handlers": [{"name": "cmd_hello"}, {"name": "cmd_orphan"}],
        "handlers_dict_keys": ["/hello", "hello"],
        "menu_commands": ["hello"],
        "help_mentions": ["/hello"],
        "guide_mentions": ["/hello"],
    }
    gaps = detect_telegram_gaps(telegram)
    orphan_gaps = [g for g in gaps if g["command"] == "orphan"]
    assert len(orphan_gaps) >= 1
    assert orphan_gaps[0]["severity"] == "P0"


def test_detects_missing_menu_entry():
    telegram = {
        "handlers": [{"name": "cmd_hello"}],
        "handlers_dict_keys": ["/hello", "hello"],
        "menu_commands": [],  # missing from menu
        "help_mentions": ["/hello"],
        "guide_mentions": ["/hello"],
    }
    gaps = detect_telegram_gaps(telegram)
    missing_menu = [g for g in gaps if "menu" in g["reason"].lower()]
    assert len(missing_menu) >= 1
