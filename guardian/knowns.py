"""Guardian's acknowledged drift — reviewed exceptions and known patterns.

This module tells Guardian which drift findings have been reviewed and
classified. Entries that remain here are accepted as intentional. Entries
removed from here will start flagging again on the next sweep.

Three kinds of acknowledgements:

1. ACCEPTED_ORPHANS — Python modules that legitimately have zero inbound
   imports (dynamically loaded, standalone utilities, experimental code
   kept around on purpose, or stubs awaiting wiring). Each entry documents
   why the orphan is acceptable.

2. PAIR_PATH_PATTERNS — structural patterns where two files with the same
   stem are expected to coexist. The CLI-wraps-iterator pattern, the
   iterator-wraps-module pattern, and scaffolded skill runners all match
   this. Each pattern is a pair of regex strings matched against
   (path_a, path_b). Patterns use `(?P<stem>...)` named groups to require
   the stems to match across the pair.

3. INTENTIONAL_PAIRS — exact path pairs that are intentionally distinct
   despite sharing a stem. Use this when the PAIR_PATH_PATTERNS mechanism
   is too broad or the relationship is unique. Tuples are
   (path_a, path_b, reason).

Update timestamps when the reason changes so reviewers can tell which
entries are stale. Guardian itself never mutates this file.
"""
from __future__ import annotations

import re

# ---------- Acknowledged orphans ----------
# Keys are repo-relative paths (forward-slash, Unix style).
# Values are free-form reasons with a date for audit tracking.
ACCEPTED_ORPHANS: dict[str, str] = {
    "cli/research.py": (
        "MarketProject — experimental per-market research project system "
        "(data/research/markets/{coin}/). Built but never integrated into "
        "the daemon or bot runtime. Candidate for deletion after review. "
        "Acknowledged 2026-04-09."
    ),
    "common/event_watcher.py": (
        "WebSocket event watcher — stub that listens to 1-min candles and "
        "feeds a ConsolidationDetector. Never wired up. Candidate for "
        "deletion after review. Acknowledged 2026-04-09."
    ),
    "common/secure_store.py": (
        "SecretsStore — AES-256-GCM encrypted vault as a cross-platform "
        "alternative to macOS Keychain. Never wired. The bot currently uses "
        "Keychain + OWS dual-write per CLAUDE.md. Candidate for deletion "
        "after review. Acknowledged 2026-04-09."
    ),
    "sdk/strategy_sdk/registry.py": (
        "ModelRegistry + StrategyBundle — versioned strategy bundle system "
        "with source-code hashing. Infrastructure built but never consumed "
        "by any loader. Candidate for deletion or integration. "
        "Acknowledged 2026-04-09."
    ),
}


# ---------- Legitimate pair patterns ----------
# Each entry is a tuple of (pattern_a, pattern_b, description). Both
# patterns must compile as regex. A pair of files matches when its two
# paths match the two patterns (in either order) AND the `stem` named
# group values agree (or both patterns use `(?P<any>.*)` if the stem
# doesn't need to match).
#
# Patterns match against repo-relative POSIX paths.
PAIR_PATH_PATTERNS: list[tuple[str, str, str]] = [
    # CLI-wraps-daemon-iterator: cli/commands/X.py + cli/daemon/iterators/X.py
    (
        r"^cli/commands/(?P<stem>[^/]+)\.py$",
        r"^cli/daemon/iterators/(?P<stem>[^/]+)\.py$",
        "CLI command wraps daemon iterator (standard pattern)",
    ),
    # Iterator-wraps-module: cli/daemon/iterators/X.py + modules/X.py
    (
        r"^cli/daemon/iterators/(?P<stem>[^/]+)\.py$",
        r"^modules/(?P<stem>[^/]+)\.py$",
        "Daemon iterator wraps pure-logic module (modules/)",
    ),
    # Iterator-wraps-common: cli/daemon/iterators/X.py + common/X.py
    (
        r"^cli/daemon/iterators/(?P<stem>[^/]+)\.py$",
        r"^common/(?P<stem>[^/]+)\.py$",
        "Daemon iterator wraps shared module (common/)",
    ),
    # Iterator with _iter suffix wraps plain module: cli/daemon/iterators/X_iter.py + (modules|common)/X.py
    (
        r"^cli/daemon/iterators/(?P<stem>[^/]+)_iter\.py$",
        r"^(?:modules|common)/(?P<stem>[^/]+)\.py$",
        "Suffix-disambiguated iterator wraps pure module",
    ),
    # Scaffolded skill runners: skills/*/scripts/standalone_runner.py
    # (all instances pair with each other; the skill dir segment differs)
    (
        r"^skills/[^/]+/scripts/standalone_runner\.py$",
        r"^skills/[^/]+/scripts/standalone_runner\.py$",
        "Scaffolded skill standalone runner (one per skill by design)",
    ),
]


# ---------- Explicit intentional pairs ----------
# Use this when PAIR_PATH_PATTERNS is too broad or the relationship is
# unique. Each tuple is (path_a, path_b, reason). Order doesn't matter.
INTENTIONAL_PAIRS: list[tuple[str, str, str]] = [
    (
        "adapters/hl_adapter.py",
        "cli/hl_adapter.py",
        "Adapter pattern — adapters/hl_adapter.py is a thin VenueAdapter "
        "bridge around cli/hl_adapter.DirectHLProxy. Intentionally separate "
        "to keep venue-agnostic code (adapters/) decoupled from direct "
        "exchange implementation (cli/).",
    ),
    (
        "cli/engine.py",
        "quoting_engine/engine.py",
        "Unrelated components sharing the 'engine' stem: cli/engine.py is "
        "TradingEngine (autonomous tick loop for direct HL trading), "
        "quoting_engine/engine.py is QuotingEngine (market-making "
        "orchestrator). No code relationship — rename would be invasive.",
    ),
]


# ---------- Helpers ----------

def is_accepted_orphan(path: str) -> bool:
    """Return True if `path` (repo-relative, POSIX) is a known orphan."""
    return path in ACCEPTED_ORPHANS


def is_intentional_pair(path_a: str, path_b: str) -> bool:
    """Return True if (path_a, path_b) is explicitly listed as intentional."""
    a, b = sorted([path_a, path_b])
    for pair_a, pair_b, _reason in INTENTIONAL_PAIRS:
        x, y = sorted([pair_a, pair_b])
        if a == x and b == y:
            return True
    return False


def matches_pair_pattern(path_a: str, path_b: str) -> bool:
    """Return True if (path_a, path_b) matches any pattern in PAIR_PATH_PATTERNS.

    A match requires both paths to match their respective regex (either
    order), AND if both patterns have a named group called 'stem', those
    groups must agree.
    """
    for pattern_a, pattern_b, _reason in PAIR_PATH_PATTERNS:
        if _pair_matches(path_a, path_b, pattern_a, pattern_b):
            return True
        # Try swapped order
        if _pair_matches(path_b, path_a, pattern_a, pattern_b):
            return True
    return False


def _pair_matches(path_a: str, path_b: str, pattern_a: str, pattern_b: str) -> bool:
    m_a = re.match(pattern_a, path_a)
    if not m_a:
        return False
    m_b = re.match(pattern_b, path_b)
    if not m_b:
        return False
    # If both patterns use 'stem', require agreement
    stem_a = m_a.groupdict().get("stem")
    stem_b = m_b.groupdict().get("stem")
    if stem_a is not None and stem_b is not None:
        return stem_a == stem_b
    return True
