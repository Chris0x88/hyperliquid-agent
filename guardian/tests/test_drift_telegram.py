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


def test_hidden_handlers_are_skipped_entirely():
    """Handlers listed in _GUARDIAN_HIDDEN_HANDLERS are intentionally
    excluded from menu/help/guide and must not produce ANY gap findings."""
    telegram = {
        "handlers": [
            {"name": "cmd_public"},
            {"name": "cmd_admin_hidden"},
        ],
        "handlers_dict_keys": ["public", "admin_hidden"],
        "handlers_dict_values": ["cmd_public", "cmd_admin_hidden"],
        "menu_commands": ["public"],
        "help_mentions": ["public"],
        "guide_mentions": ["public"],
        "hidden_handlers": ["cmd_admin_hidden"],
    }
    gaps = detect_telegram_gaps(telegram)
    # cmd_admin_hidden should be completely absent — not P0, not P1, not P2
    assert all(g["command"] != "admin_hidden" for g in gaps), (
        f"Hidden handler leaked into drift report: {gaps}"
    )
    # cmd_public is fully registered so no gaps at all
    assert gaps == [], f"Expected no gaps, got: {gaps}"


def test_menu_exempt_handlers_skip_menu_check():
    """Handlers in _GUARDIAN_MENU_EXEMPT are intentionally NOT in the menu
    (help-only commands). Drift should not flag them for the menu gap,
    but still flags them for help/guide gaps."""
    telegram = {
        "handlers": [{"name": "cmd_advanced"}],
        "handlers_dict_keys": ["advanced"],
        "handlers_dict_values": ["cmd_advanced"],
        "menu_commands": [],  # intentionally empty
        "help_mentions": ["advanced"],
        "guide_mentions": ["advanced"],
        "menu_exempt_handlers": ["cmd_advanced"],
    }
    gaps = detect_telegram_gaps(telegram)
    assert gaps == [], f"Expected no gaps for menu-exempt handler: {gaps}"


def test_menu_exempt_still_flags_missing_help():
    """Menu-exempt doesn't mean help-exempt."""
    telegram = {
        "handlers": [{"name": "cmd_advanced"}],
        "handlers_dict_keys": ["advanced"],
        "handlers_dict_values": ["cmd_advanced"],
        "menu_commands": [],
        "help_mentions": [],  # missing from help
        "guide_mentions": ["advanced"],
        "menu_exempt_handlers": ["cmd_advanced"],
    }
    gaps = detect_telegram_gaps(telegram)
    # Should flag missing from help, but NOT missing from menu
    assert len(gaps) == 1
    assert "cmd_help" in gaps[0]["missing_from"]
    assert "_set_telegram_commands() menu" not in gaps[0]["missing_from"]
