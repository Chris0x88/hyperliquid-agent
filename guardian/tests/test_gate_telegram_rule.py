"""Tests for the telegram-completeness gate rule."""
from __future__ import annotations

from pathlib import Path

from guardian.gate import check_tool_use


def test_rule_allows_edit_to_unrelated_file():
    result = check_tool_use(
        tool_name="Edit",
        tool_input={"file_path": "some/other/file.py", "old_string": "x", "new_string": "y"},
    )
    assert result.allow is True


def test_rule_allows_full_registration(tmp_path: Path, monkeypatch):
    tg = tmp_path / "cli" / "telegram_bot.py"
    tg.parent.mkdir(parents=True)
    tg.write_text("""
def cmd_new(token, chat_id, args):
    return "new"

def cmd_help(token, chat_id, args):
    return "/new - new /help - help /guide - guide"

def cmd_guide(token, chat_id, args):
    return "/new - new /help - help /guide - guide"

HANDLERS = {
    "/new": cmd_new,
    "new": cmd_new,
    "/help": cmd_help,
    "help": cmd_help,
    "/guide": cmd_guide,
    "guide": cmd_guide,
}

def _set_telegram_commands():
    return [
        {"command": "new", "description": "new cmd"},
        {"command": "help", "description": "help cmd"},
        {"command": "guide", "description": "guide cmd"},
    ]
""")
    monkeypatch.chdir(tmp_path)
    result = check_tool_use(
        tool_name="Edit",
        tool_input={"file_path": str(tg), "old_string": "x", "new_string": "y"},
    )
    assert result.allow is True


def test_rule_blocks_new_handler_without_registration(tmp_path: Path, monkeypatch):
    tg = tmp_path / "cli" / "telegram_bot.py"
    tg.parent.mkdir(parents=True)
    tg.write_text("""
def cmd_orphan(token, chat_id, args):
    return "orphan"

HANDLERS = {}

def _set_telegram_commands():
    return []

def cmd_help(token, chat_id, args):
    return ""

def cmd_guide(token, chat_id, args):
    return ""
""")
    monkeypatch.chdir(tmp_path)
    result = check_tool_use(
        tool_name="Write",
        tool_input={"file_path": str(tg), "content": tg.read_text()},
    )
    assert result.allow is False
    assert "cmd_orphan" in (result.reason or "")
    assert result.rule == "telegram-completeness"


def test_rule_respects_kill_switch(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("GUARDIAN_RULE_TELEGRAM_COMPLETENESS", "0")
    tg = tmp_path / "cli" / "telegram_bot.py"
    tg.parent.mkdir(parents=True)
    tg.write_text("def cmd_orphan(token, chat_id, args): return 'x'\nHANDLERS = {}\n")
    monkeypatch.chdir(tmp_path)
    result = check_tool_use(
        tool_name="Write",
        tool_input={"file_path": str(tg), "content": tg.read_text()},
    )
    assert result.allow is True
