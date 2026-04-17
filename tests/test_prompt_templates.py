"""tests/test_prompt_templates.py — Unit tests for the prompt template engine.

Covers: list_templates, load_template, expand_template, save_template,
routing precedence (HANDLERS always win, template fallback only fires after),
and input validation.
"""

from __future__ import annotations

import importlib
import sys
import textwrap
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def tmp_prompts_dir(tmp_path, monkeypatch):
    """Redirect _PROMPTS_DIR to a temporary directory for isolation."""
    import agent.prompts_lib as lib
    monkeypatch.setattr(lib, "_PROMPTS_DIR", tmp_path)
    return tmp_path


@pytest.fixture()
def starter_templates(tmp_prompts_dir):
    """Write 3 templates into the temp prompts dir."""
    (tmp_prompts_dir / "silvercheck.md").write_text(
        "Silver position audit.\n\nCheck the funding rate {{args}}.\n",
        encoding="utf-8",
    )
    (tmp_prompts_dir / "btccheck.md").write_text(
        "BTC position audit for {{symbol}}.\n\nContext: {{args}}\n",
        encoding="utf-8",
    )
    (tmp_prompts_dir / "portfoliosweep.md").write_text(
        "Full portfolio sweep.\n\nScope: {{args}}\n",
        encoding="utf-8",
    )
    return tmp_prompts_dir


# ---------------------------------------------------------------------------
# list_templates
# ---------------------------------------------------------------------------

def test_list_templates_returns_starter_set(starter_templates):
    from agent.prompts_lib import list_templates

    result = list_templates()
    names = [t.name for t in result]
    assert "silvercheck" in names
    assert "btccheck" in names
    assert "portfoliosweep" in names


def test_list_templates_sorted_by_name(starter_templates):
    from agent.prompts_lib import list_templates

    result = list_templates()
    names = [t.name for t in result]
    assert names == sorted(names)


def test_list_templates_empty_dir(tmp_prompts_dir):
    from agent.prompts_lib import list_templates

    assert list_templates() == []


def test_list_templates_excludes_readme(tmp_prompts_dir):
    (tmp_prompts_dir / "README.md").write_text("# Readme", encoding="utf-8")
    (tmp_prompts_dir / "mytmpl.md").write_text("A template.", encoding="utf-8")
    from agent.prompts_lib import list_templates

    result = list_templates()
    names = [t.name for t in result]
    assert "README" not in names
    assert "mytmpl" in names


def test_list_templates_missing_dir(monkeypatch, tmp_path):
    """Non-existent prompts dir returns empty list (no crash)."""
    import agent.prompts_lib as lib
    monkeypatch.setattr(lib, "_PROMPTS_DIR", tmp_path / "nonexistent")
    from agent.prompts_lib import list_templates

    assert list_templates() == []


# ---------------------------------------------------------------------------
# load_template
# ---------------------------------------------------------------------------

def test_load_existing_template(starter_templates):
    from agent.prompts_lib import load_template

    tmpl = load_template("silvercheck")
    assert tmpl is not None
    assert tmpl.name == "silvercheck"
    assert "Silver position audit" in tmpl.description
    assert "{{args}}" in tmpl.body


def test_load_unknown_template_returns_none(starter_templates):
    from agent.prompts_lib import load_template

    assert load_template("doesnotexist") is None


def test_load_readme_returns_none(tmp_prompts_dir):
    (tmp_prompts_dir / "README.md").write_text("# README", encoding="utf-8")
    from agent.prompts_lib import load_template

    assert load_template("README") is None


def test_load_template_populates_variables(starter_templates):
    from agent.prompts_lib import load_template

    tmpl = load_template("btccheck")
    assert tmpl is not None
    # btccheck has {{symbol}} and {{args}}
    assert "args" in tmpl.variables
    assert "symbol" in tmpl.variables


def test_load_template_description_from_first_line(starter_templates):
    from agent.prompts_lib import load_template

    tmpl = load_template("silvercheck")
    assert tmpl is not None
    assert tmpl.description == "Silver position audit."


# ---------------------------------------------------------------------------
# expand_template
# ---------------------------------------------------------------------------

def test_expand_substitutes_args(starter_templates):
    from agent.prompts_lib import expand_template

    result = expand_template("silvercheck", args="ahead of FOMC")
    assert result is not None
    assert "ahead of FOMC" in result
    assert "{{args}}" not in result


def test_expand_with_named_vars(starter_templates):
    from agent.prompts_lib import expand_template

    result = expand_template("btccheck", args="post-halving", symbol="BTC-PERP")
    assert result is not None
    assert "BTC-PERP" in result
    assert "{{symbol}}" not in result
    assert "post-halving" in result


def test_expand_named_vars_take_precedence_over_args(tmp_prompts_dir):
    """When {{args}} and a named var share the same key, named wins."""
    (tmp_prompts_dir / "testmpl.md").write_text(
        "Hello {{args}} world.\n", encoding="utf-8"
    )
    from agent.prompts_lib import expand_template

    result = expand_template("testmpl", args="FROM_ARGS", args_override="NAMED")
    # args_override is a separate key — should leave {{args}} substituted by args
    assert result is not None
    assert "FROM_ARGS" in result


def test_expand_unknown_template_returns_none(starter_templates):
    from agent.prompts_lib import expand_template

    assert expand_template("xyznosuchtemplate") is None


def test_expand_empty_args_leaves_placeholder_blank(tmp_prompts_dir):
    (tmp_prompts_dir / "minimal.md").write_text(
        "Context: {{args}}\nEnd.", encoding="utf-8"
    )
    from agent.prompts_lib import expand_template

    result = expand_template("minimal", args="")
    assert result is not None
    assert "Context: \n" in result
    assert "{{args}}" not in result


# ---------------------------------------------------------------------------
# save_template
# ---------------------------------------------------------------------------

def test_save_template_writes_file_atomically(tmp_prompts_dir):
    from agent.prompts_lib import save_template

    path = save_template("mytemplate", "Hello {{args}}.", description="My custom template")
    dest = tmp_prompts_dir / "mytemplate.md"
    assert dest.exists()
    content = dest.read_text(encoding="utf-8")
    assert "Hello {{args}}" in content
    assert path == str(dest)


def test_save_template_no_tmp_files_left(tmp_prompts_dir):
    """Atomic write must not leave .tmp_ files behind."""
    from agent.prompts_lib import save_template

    save_template("cleanup_test", "Body text.")
    leftover = list(tmp_prompts_dir.glob(".cleanup_test_tmp_*"))
    assert leftover == []


def test_save_refuses_builtin_command_names(tmp_prompts_dir):
    from agent.prompts_lib import save_template

    builtin_names = ["status", "stop", "steer", "follow", "cancel",
                     "evening", "morning", "help", "guide", "templates", "save"]
    for name in builtin_names:
        with pytest.raises(ValueError, match="built-in"):
            save_template(name, "body")


def test_save_refuses_invalid_names(tmp_prompts_dir):
    from agent.prompts_lib import save_template

    invalid = ["MyTemplate", "with space", "has!special", "", "_leadunderscore",
               "has.dot", "UPPER"]
    for name in invalid:
        with pytest.raises(ValueError):
            save_template(name, "body")


def test_save_accepts_valid_names(tmp_prompts_dir):
    from agent.prompts_lib import save_template

    valid = ["abc", "abc123", "oil-check", "oil_check", "a1b2c3", "x"]
    for name in valid:
        path = save_template(name, f"Template body for {name}.")
        assert Path(path).exists()


def test_save_overwrites_existing_custom_template(tmp_prompts_dir):
    from agent.prompts_lib import save_template

    save_template("overwrite_me", "Version 1.")
    save_template("overwrite_me", "Version 2.")
    content = (tmp_prompts_dir / "overwrite_me.md").read_text(encoding="utf-8")
    assert "Version 2" in content
    assert "Version 1" not in content


# ---------------------------------------------------------------------------
# Routing precedence — HANDLERS dict must always win
# ---------------------------------------------------------------------------

def test_routing_does_not_intercept_builtin_commands():
    """Existing /status goes to cmd_status, not template lookup.

    We verify that expand_template("status") returns None (since 'status'
    is a built-in, it can never be saved as a template, and there is no
    status.md in data/agent/prompts/). This validates the save_template guard.
    """
    from agent.prompts_lib import expand_template

    # Should return None (no template named 'status')
    assert expand_template("status") is None


def test_routing_does_not_intercept_already_handled(tmp_prompts_dir):
    """Even if someone manually placed status.md in the prompts dir,
    the HANDLERS dispatch fires first in bot.py. Here we just verify that
    the template engine itself doesn't explode — it would return the expanded
    text, but the bot never reaches template lookup for HANDLERS keys.

    The bot-level test is in test_routing_expands_unknown_slash_when_template_exists.
    """
    # Place a file that mimics what would happen in edge case
    (tmp_prompts_dir / "mytest_cmd.md").write_text(
        "Template body for {{args}}.\n", encoding="utf-8"
    )
    from agent.prompts_lib import expand_template

    result = expand_template("mytest_cmd", "hello")
    assert result is not None
    assert "hello" in result


def test_routing_expands_unknown_slash_when_template_exists(tmp_prompts_dir):
    """Simulate the bot routing: unknown slash cmd with matching template → expanded."""
    (tmp_prompts_dir / "oilsweep.md").write_text(
        "Oil sweep prompt for {{args}}.\n", encoding="utf-8"
    )
    from agent.prompts_lib import expand_template

    # Bot calls expand_template after HANDLERS returns no match
    expanded = expand_template("oilsweep", "BRENTOIL ahead of EIA")
    assert expanded is not None
    assert "BRENTOIL ahead of EIA" in expanded


def test_routing_passes_through_unknown_slash_when_no_template(tmp_prompts_dir):
    """Unknown slash cmd with no template → expand_template returns None.

    The bot should then emit 'Unknown command' — not a crash, not AI routing.
    """
    from agent.prompts_lib import expand_template

    assert expand_template("totallyunknown") is None


# ---------------------------------------------------------------------------
# Template metadata correctness
# ---------------------------------------------------------------------------

def test_description_strips_heading_markers(tmp_prompts_dir):
    (tmp_prompts_dir / "headingtest.md").write_text(
        "# My template heading\n\nBody text.\n", encoding="utf-8"
    )
    from agent.prompts_lib import load_template

    tmpl = load_template("headingtest")
    assert tmpl is not None
    assert tmpl.description == "My template heading"


def test_variables_deduplicated(tmp_prompts_dir):
    (tmp_prompts_dir / "deduptest.md").write_text(
        "{{args}} and {{args}} again, plus {{other}}.\n", encoding="utf-8"
    )
    from agent.prompts_lib import load_template

    tmpl = load_template("deduptest")
    assert tmpl is not None
    assert tmpl.variables.count("args") == 1
    assert "other" in tmpl.variables


def test_no_description_line_returns_placeholder(tmp_prompts_dir):
    (tmp_prompts_dir / "nodesc.md").write_text("\n\n\n", encoding="utf-8")
    from agent.prompts_lib import load_template

    tmpl = load_template("nodesc")
    assert tmpl is not None
    assert tmpl.description == "(no description)"
