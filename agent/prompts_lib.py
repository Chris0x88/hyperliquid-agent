"""prompts_lib.py — pi-mono-style prompt template engine.

Templates live in data/agent/prompts/<name>.md.
They support {{var}} substitution: {{args}} is always populated from the raw
command remainder (e.g. "/silvercheck BTC 5m" → args="BTC 5m"), and any
named {{var}} placeholders can be overridden by keyword arguments to
expand_template().

Slash commands registered in HANDLERS always win — save_template() refuses
to overwrite any built-in command name. Template expansion only fires AFTER
the existing HANDLERS dispatch returns no match (see telegram/bot.py).
"""

from __future__ import annotations

import re
import tempfile
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

# Location of template files, relative to the project root (agent-cli/).
# Resolved once at module-load time — tests may monkey-patch _PROMPTS_DIR.
_PROMPTS_DIR = Path(__file__).resolve().parent.parent / "data" / "agent" / "prompts"

# ── Name validation ────────────────────────────────────────────────────────────

_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]*$")

# All built-in HANDLERS command names (bare form, no leading /).
# This list is conservative — it includes every key in the HANDLERS dict that
# a malicious or accidental template could shadow.  We also include the two
# new built-in names /templates and /save themselves.
_BUILTIN_NAMES: frozenset[str] = frozenset({
    "status", "price", "orders", "pnl", "commands", "chart", "market", "m",
    "position", "pos", "bug", "todo", "feedback", "fb", "feedback_resolve",
    "fbr", "memory", "mem", "diag", "watchlist", "w", "powerlaw",
    "rebalancer", "rebalance", "brief", "b", "briefai", "bai", "restart",
    "restartall", "signals", "sig", "delegate", "reclaim", "authority",
    "auth", "help", "guide", "g", "models", "model", "health", "h",
    "thesis", "news", "catalysts", "supply", "disruptions", "disrupt",
    "heatmap", "botpatterns", "oilbot", "oilbotjournal", "oilbotreviewai",
    "selftune", "selftuneproposals", "selftuneapprove", "selftunereject",
    "lab", "architect", "patterncatalog", "patternpromote", "patternreject",
    "shadoweval", "sim", "readiness", "activate", "adaptlog", "lessons",
    "lesson", "lessonsearch", "lessonauthorai", "brutalreviewai", "critique",
    "chathistory", "ch", "nudge", "menu", "close", "sl", "tp", "start",
    "evening", "eve", "morning", "morn", "stop", "steer", "cancel", "follow",
    "agentstate", "as", "addmarket", "removemarket", "disrupt-update",
    # new built-ins added by this feature
    "templates", "save",
})


# ── Data class ─────────────────────────────────────────────────────────────────


@dataclass
class Template:
    name: str          # e.g. "silvercheck"
    path: str          # absolute path to the .md file
    body: str          # raw markdown content
    description: str   # first non-blank line OR "(no description)"
    variables: list[str] = field(default_factory=list)  # parsed {{var}} placeholders


def _extract_description(body: str) -> str:
    """Return the first non-blank, non-comment line of the body."""
    for line in body.splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith("<!--"):
            # Strip markdown heading markers for cleaner description
            return stripped.lstrip("#").strip()
    return "(no description)"


def _extract_variables(body: str) -> list[str]:
    """Return a deduplicated list of {{var}} placeholders found in body."""
    seen: dict[str, None] = {}
    for m in re.finditer(r"\{\{(\w+)\}\}", body):
        seen[m.group(1)] = None
    return list(seen)


def _load_from_path(path: Path) -> Template:
    """Parse a single template file into a Template dataclass."""
    body = path.read_text(encoding="utf-8")
    return Template(
        name=path.stem,
        path=str(path),
        body=body,
        description=_extract_description(body),
        variables=_extract_variables(body),
    )


# ── Public API ─────────────────────────────────────────────────────────────────


def list_templates() -> list[Template]:
    """Return all .md templates in the prompts directory, sorted by name."""
    if not _PROMPTS_DIR.exists():
        return []
    return sorted(
        (_load_from_path(p) for p in _PROMPTS_DIR.glob("*.md") if p.stem != "README"),
        key=lambda t: t.name,
    )


def load_template(name: str) -> Optional[Template]:
    """Load a single template by name (without .md extension).

    Returns None if not found.  README is not a valid template name.
    """
    if not name or name.upper() == "README":
        return None
    path = _PROMPTS_DIR / f"{name}.md"
    if not path.exists():
        return None
    return _load_from_path(path)


def expand_template(name: str, args: str = "", **vars: str) -> Optional[str]:
    """Return the expanded prompt body or None if the template doesn't exist.

    Substitution rules (in precedence order):
      1. Named keyword arguments override everything.
      2. {{args}} is populated from the raw *args* string.
      3. Any remaining {{var}} placeholders are left as-is (not stripped).

    Args:
        name: template name (file stem, no .md)
        args: raw remainder after the slash command (e.g. "BTC 5m")
        **vars: named substitutions that override {{args}} for the same key
    """
    tmpl = load_template(name)
    if tmpl is None:
        return None

    text = tmpl.body
    # Apply named vars first (highest priority)
    for key, val in vars.items():
        text = text.replace(f"{{{{{key}}}}}", val)
    # Then apply args to any remaining {{args}} placeholder
    if "{{args}}" in text:
        text = text.replace("{{args}}", args)
    return text


def save_template(name: str, body: str, description: str = "") -> str:
    """Write data/agent/prompts/<name>.md atomically.

    Returns the absolute file path on success.

    Raises:
        ValueError: if name collides with a built-in command or is invalid.
        OSError: on write failure.
    """
    # Validate name
    if not _NAME_RE.match(name):
        raise ValueError(
            f"Invalid template name {name!r}. "
            "Use only lowercase letters, digits, hyphens, and underscores "
            "(must start with a letter or digit)."
        )
    if name in _BUILTIN_NAMES:
        raise ValueError(
            f"Cannot save template {name!r}: conflicts with a built-in command. "
            "Choose a different name."
        )

    _PROMPTS_DIR.mkdir(parents=True, exist_ok=True)
    dest = _PROMPTS_DIR / f"{name}.md"

    # Prepend description as a comment header if provided and body doesn't
    # already start with it
    final_body = body
    if description and not body.strip().startswith(description):
        # Just write the description as the first line if it's not there
        final_body = f"{description}\n\n{body}" if body.strip() else description

    # Atomic write: temp file in same dir → rename
    tmp_fd, tmp_path = tempfile.mkstemp(dir=str(_PROMPTS_DIR), prefix=f".{name}_tmp_")
    try:
        with os.fdopen(tmp_fd, "w", encoding="utf-8") as f:
            f.write(final_body)
        os.replace(tmp_path, str(dest))
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise

    return str(dest)
