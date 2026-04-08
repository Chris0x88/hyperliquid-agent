"""Tests for cartographer's Telegram command scanning."""
from __future__ import annotations

from pathlib import Path

from guardian.cartographer import scan_telegram_commands

FIXTURE = Path(__file__).parent / "fixtures" / "fake_telegram_bot.py"


def test_scan_finds_all_cmd_handlers():
    result = scan_telegram_commands(FIXTURE)
    handlers = {h["name"] for h in result["handlers"]}
    # cmd_help and cmd_guide are also cmd_* defs in the fixture
    assert handlers == {"cmd_hello", "cmd_goodbye", "cmd_orphan", "cmd_help", "cmd_guide"}


def test_scan_finds_commands_in_handlers_dict():
    result = scan_telegram_commands(FIXTURE)
    assert "/hello" in result["handlers_dict_keys"]
    assert "/goodbye" in result["handlers_dict_keys"]


def test_scan_finds_set_telegram_commands_entries():
    result = scan_telegram_commands(FIXTURE)
    menu_cmds = set(result["menu_commands"])
    assert menu_cmds == {"hello", "goodbye"}


def test_scan_finds_help_entries():
    result = scan_telegram_commands(FIXTURE)
    help_mentions = set(result["help_mentions"])
    assert "hello" in help_mentions
    assert "goodbye" in help_mentions


def test_scan_detects_unregistered_handler():
    result = scan_telegram_commands(FIXTURE)
    handler_names = {h["name"] for h in result["handlers"]}
    dict_keys = {k.lstrip("/") for k in result["handlers_dict_keys"]}
    unregistered = {
        h.replace("cmd_", "")
        for h in handler_names
        if h.replace("cmd_", "") not in dict_keys
    }
    assert "orphan" in unregistered
