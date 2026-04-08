"""Tests for drift.detect_telegram_gaps()."""
from __future__ import annotations

from guardian.drift import detect_telegram_gaps


def test_no_gaps_when_fully_registered():
    telegram = {
        "handlers": [{"name": "cmd_hello"}, {"name": "cmd_bye"}],
        "handlers_dict_keys": ["/hello", "hello", "/bye", "bye"],
        "handlers_dict_values": ["cmd_hello", "cmd_hello", "cmd_bye", "cmd_bye"],
        "menu_commands": ["hello", "bye"],
        "help_mentions": ["hello", "bye"],
        "guide_mentions": ["hello", "bye"],
    }
    gaps = detect_telegram_gaps(telegram)
    assert gaps == []


def test_detects_unregistered_handler():
    telegram = {
        "handlers": [{"name": "cmd_hello"}, {"name": "cmd_orphan"}],
        "handlers_dict_keys": ["/hello", "hello"],
        "handlers_dict_values": ["cmd_hello", "cmd_hello"],
        "menu_commands": ["hello"],
        "help_mentions": ["hello"],
        "guide_mentions": ["hello"],
    }
    gaps = detect_telegram_gaps(telegram)
    orphan_gaps = [g for g in gaps if g["command"] == "orphan"]
    assert len(orphan_gaps) >= 1
    assert orphan_gaps[0]["severity"] == "P0"


def test_detects_missing_menu_entry():
    telegram = {
        "handlers": [{"name": "cmd_hello"}],
        "handlers_dict_keys": ["/hello", "hello"],
        "handlers_dict_values": ["cmd_hello", "cmd_hello"],
        "menu_commands": [],  # missing from menu
        "help_mentions": ["hello"],
        "guide_mentions": ["hello"],
    }
    gaps = detect_telegram_gaps(telegram)
    missing_menu = [g for g in gaps if "menu" in g["reason"].lower()]
    assert len(missing_menu) >= 1


def test_handler_registered_under_different_key_not_flagged():
    """The Guardian bug caught on first real-repo sweep.

    cmd_addmarket_confirm was falsely flagged P0 because HANDLERS used
    the key `addmarket!` which didn't match the stripped handler name
    `addmarket_confirm`. The authoritative check is: does the function
    appear as a VALUE in HANDLERS?
    """
    telegram = {
        "handlers": [{"name": "cmd_addmarket_confirm"}],
        "handlers_dict_keys": ["addmarket!"],  # key is NOT addmarket_confirm
        "handlers_dict_values": ["cmd_addmarket_confirm"],  # but the fn is routed
        "menu_commands": [],
        "help_mentions": [],
        "guide_mentions": [],
    }
    gaps = detect_telegram_gaps(telegram)
    # Should NOT be flagged as a P0 (routing exists). It's an internal
    # continuation so the menu/help/guide checks get downgraded to P2.
    p0 = [g for g in gaps if g.get("severity") == "P0"]
    assert p0 == [], f"False positive P0 on routed handler: {p0}"


def test_hyphen_key_still_routes():
    """cmd_disrupt_update was falsely flagged because HANDLERS used
    'disrupt-update' (hyphen) which didn't match the stripped name
    'disrupt_update' (underscore). The value-based check handles it."""
    telegram = {
        "handlers": [{"name": "cmd_disrupt_update"}],
        "handlers_dict_keys": ["disrupt-update"],
        "handlers_dict_values": ["cmd_disrupt_update"],
        "menu_commands": [],
        "help_mentions": [],
        "guide_mentions": [],
    }
    gaps = detect_telegram_gaps(telegram)
    p0 = [g for g in gaps if g.get("severity") == "P0"]
    assert p0 == [], f"False positive P0 on hyphen-keyed handler: {p0}"
