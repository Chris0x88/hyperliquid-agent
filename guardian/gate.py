"""Guardian review gate — PreToolUse checks on Edit/Write/Bash.

Pure stdlib. Must be fast (<100ms per call). Fail-open on any error —
Guardian's gate never blocks Claude Code itself from running.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable


# ---------- Kill switches ----------

def is_enabled() -> bool:
    return os.environ.get("GUARDIAN_GATE_ENABLED", "1") != "0"


def is_rule_enabled(rule_name: str) -> bool:
    env_name = "GUARDIAN_RULE_" + rule_name.upper().replace("-", "_")
    if os.environ.get(env_name, "1") == "0":
        return False
    # Also check a short alias that drops a trailing _WARNING/_GUARD suffix
    # so kill switches can use concise names like GUARDIAN_RULE_PARALLEL_TRACK
    # for a rule registered as parallel-track-warning.
    for suffix in ("_WARNING", "_GUARD"):
        if env_name.endswith(suffix):
            short = env_name[: -len(suffix)]
            if os.environ.get(short, "1") == "0":
                return False
            break
    return True


# ---------- Result type ----------

@dataclass
class GateResult:
    """Outcome of a gate check."""
    allow: bool
    reason: str | None = None
    rule: str | None = None


# ---------- Rule registry ----------

RuleFn = Callable[[str, dict[str, Any]], "GateResult | None"]
_RULES: list[tuple[str, RuleFn]] = []


def register_rule(name: str):
    """Decorator to register a rule function under a name."""
    def decorator(fn: RuleFn) -> RuleFn:
        _RULES.append((name, fn))
        return fn
    return decorator


# ---------- Main check entrypoint ----------

def check_tool_use(tool_name: str, tool_input: dict[str, Any]) -> GateResult:
    """Run all enabled gate rules against a tool call.

    Returns the first block result, or GateResult(allow=True) if all pass.
    """
    if not is_enabled():
        return GateResult(allow=True, reason="Guardian gate globally disabled")

    for rule_name, rule_fn in _RULES:
        if not is_rule_enabled(rule_name):
            continue
        try:
            result = rule_fn(tool_name, tool_input)
        except Exception:
            # Fail-open on rule error
            continue
        if result is not None and not result.allow:
            return result

    return GateResult(allow=True)


# ---------- Rule: telegram-completeness ----------

@register_rule("telegram-completeness")
def _rule_telegram_completeness(tool_name: str, tool_input: dict[str, Any]) -> GateResult | None:
    """Block Edit/Write to telegram_bot.py that adds a cmd_X without registration."""
    if tool_name not in ("Edit", "Write"):
        return None

    file_path = tool_input.get("file_path", "")
    if not file_path:
        return None

    path = Path(file_path)
    if path.name != "telegram_bot.py":
        return None

    # Determine the future content of the file
    if tool_name == "Write":
        future_content = tool_input.get("content", "")
    else:  # Edit
        if not path.exists():
            return None
        try:
            current = path.read_text(encoding="utf-8")
        except OSError:
            return None
        old = tool_input.get("old_string", "")
        new = tool_input.get("new_string", "")
        if not old:
            return None
        replace_all = bool(tool_input.get("replace_all", False))
        if replace_all:
            future_content = current.replace(old, new)
        else:
            future_content = current.replace(old, new, 1)

    # Import the scanner lazily to keep hook startup fast
    from guardian.cartographer import scan_telegram_commands

    tmp_path = path.parent / f".{path.name}.guardian.tmp"
    try:
        tmp_path.write_text(future_content, encoding="utf-8")
        scan = scan_telegram_commands(tmp_path)
    finally:
        try:
            tmp_path.unlink()
        except OSError:
            pass

    handler_names = {h["name"].replace("cmd_", "") for h in scan.get("handlers", [])}
    dict_keys = {k.lstrip("/") for k in scan.get("handlers_dict_keys", [])}
    menu = set(scan.get("menu_commands", []))
    help_set = {h.lstrip("/") for h in scan.get("help_mentions", [])}
    guide_set = {h.lstrip("/") for h in scan.get("guide_mentions", [])}

    missing: list[str] = []
    for cmd in sorted(handler_names):
        gaps = []
        if cmd not in dict_keys:
            gaps.append("HANDLERS dict")
        if cmd not in menu:
            gaps.append("_set_telegram_commands() menu")
        if cmd not in help_set:
            gaps.append("cmd_help")
        if cmd not in guide_set:
            gaps.append("cmd_guide")
        if gaps:
            missing.append(f"cmd_{cmd}: missing from {', '.join(gaps)}")

    if missing:
        return GateResult(
            allow=False,
            rule="telegram-completeness",
            reason=(
                "Telegram command registration incomplete. "
                "Per CLAUDE.md, every new command must be registered in "
                "HANDLERS, _set_telegram_commands(), cmd_help, and cmd_guide. "
                "Missing:\n  " + "\n  ".join(missing)
            ),
        )

    return None


# ---------- Rule: parallel-track-warning ----------

@register_rule("parallel-track-warning")
def _rule_parallel_track_warning(tool_name: str, tool_input: dict[str, Any]) -> GateResult | None:
    """Warn when creating a new .py file with a name overlapping an existing one."""
    if tool_name != "Write":
        return None

    file_path = tool_input.get("file_path", "")
    if not file_path.endswith(".py"):
        return None

    path = Path(file_path)
    if path.exists():
        # Not a new file
        return None

    # Scan nearby .py files (same dir + repo root + one level down)
    search_dirs: list[Path] = []
    cwd = Path.cwd()
    search_dirs.append(cwd)
    if path.parent != cwd:
        search_dirs.append(path.parent)

    existing_names: set[str] = set()
    for d in search_dirs:
        if not d.exists():
            continue
        for f in d.glob("*.py"):
            if f == path:
                continue
            existing_names.add(f.stem)
        # One level down
        for sub in d.glob("*/*.py"):
            if sub == path:
                continue
            existing_names.add(sub.stem)

    from guardian.drift import _similarity

    new_stem = path.stem
    matches: list[tuple[str, float]] = []
    for other in existing_names:
        sim = _similarity(new_stem, other)
        if sim >= 0.6:
            matches.append((other, sim))

    if matches:
        matches.sort(key=lambda t: -t[1])
        top = matches[0]
        return GateResult(
            allow=False,
            rule="parallel-track-warning",
            reason=(
                f"Creating '{path.name}' but a similar file exists: "
                f"'{top[0]}.py' (similarity {top[1]:.0%}). "
                f"Possible parallel track. Merge into the existing file or "
                f"set GUARDIAN_RULE_PARALLEL_TRACK=0 to override."
            ),
        )
    return None


# ---------- Rule: recent-delete-guard ----------

import re as _re
import time as _time

_RM_RE = _re.compile(r"\brm\s+(?:-[a-zA-Z]+\s+)?([^\s;&|]+)")


@register_rule("recent-delete-guard")
def _rule_recent_delete_guard(tool_name: str, tool_input: dict[str, Any]) -> GateResult | None:
    """Block `rm` of files that were created or modified in the last 7 days."""
    if tool_name != "Bash":
        return None

    cmd = tool_input.get("command", "")
    if "rm " not in cmd and not cmd.strip().startswith("rm "):
        return None

    targets: list[str] = _RM_RE.findall(cmd)
    if not targets:
        return None

    threshold = _time.time() - 7 * 86400
    recent_hits: list[str] = []
    for t in targets:
        p = Path(t)
        if not p.exists():
            continue
        try:
            mtime = p.stat().st_mtime
        except OSError:
            continue
        if mtime > threshold:
            recent_hits.append(str(p))

    if recent_hits:
        return GateResult(
            allow=False,
            rule="recent-delete-guard",
            reason=(
                f"Blocking `rm` of file(s) modified in the last 7 days: "
                f"{', '.join(recent_hits)}. "
                f"Confirm with user or set GUARDIAN_RULE_RECENT_DELETE=0 to override."
            ),
        )
    return None


# ---------- Session state: track which files have been Read this session ----------
#
# The session_start hook writes a marker file; each Read tool call via a
# companion hook (future) or explicit mark_file_read() call updates it.
# For Phase 1 we expose mark_file_read as a public helper and tests use it
# directly. Phase 5 can wire a PostToolUse hook to auto-mark Read calls.

_SESSION_READS_FILE = Path("/tmp/guardian_session_reads.txt")


def reset_session_reads() -> None:
    """Clear the in-session read tracker (used at session start and in tests)."""
    try:
        if _SESSION_READS_FILE.exists():
            _SESSION_READS_FILE.unlink()
    except OSError:
        pass


def mark_file_read(path: str) -> None:
    """Record that a file has been Read during this session."""
    try:
        _SESSION_READS_FILE.parent.mkdir(parents=True, exist_ok=True)
        with _SESSION_READS_FILE.open("a", encoding="utf-8") as f:
            f.write(str(Path(path).resolve()) + "\n")
    except OSError:
        pass


def _has_been_read(name: str) -> bool:
    """True if any Read target's path ends with `name`."""
    if not _SESSION_READS_FILE.exists():
        return False
    try:
        lines = _SESSION_READS_FILE.read_text(encoding="utf-8").splitlines()
    except OSError:
        return False
    return any(line.endswith(name) for line in lines if line)


# ---------- Rule: stale-adr-guard ----------

@register_rule("stale-adr-guard")
def _rule_stale_adr_guard(tool_name: str, tool_input: dict[str, Any]) -> GateResult | None:
    """Block Edit/Write to docs/wiki/decisions/ without MASTER_PLAN + AUDIT_FIX_PLAN reads."""
    if tool_name not in ("Edit", "Write"):
        return None

    file_path = tool_input.get("file_path", "")
    if "/docs/wiki/decisions/" not in file_path and "\\docs\\wiki\\decisions\\" not in file_path:
        return None

    missing: list[str] = []
    if not _has_been_read("MASTER_PLAN.md"):
        missing.append("docs/plans/MASTER_PLAN.md")
    if not _has_been_read("AUDIT_FIX_PLAN.md"):
        missing.append("docs/plans/AUDIT_FIX_PLAN.md")

    if missing:
        return GateResult(
            allow=False,
            rule="stale-adr-guard",
            reason=(
                "Attempting to write an ADR without reading required context first. "
                "Per CLAUDE.md and the 2026-04-07 postmortem, ADRs must be written "
                "against current state. Read these files first:\n  "
                + "\n  ".join(missing)
                + "\n\nThen retry. Or set GUARDIAN_RULE_STALE_ADR=0 to override."
            ),
        )
    return None
