"""Tests for the guardian.knowns helpers and the drift integration."""
from __future__ import annotations

from guardian.knowns import (
    is_accepted_orphan,
    is_intentional_pair,
    matches_pair_pattern,
)
from guardian.drift import detect_orphans, detect_parallel_tracks


# ---------- guardian.knowns helpers ----------

def test_accepted_orphan_lookup():
    assert is_accepted_orphan("cli/research.py") is True
    assert is_accepted_orphan("cli/telegram_bot.py") is False


def test_intentional_pair_exact_match():
    assert is_intentional_pair("adapters/hl_adapter.py", "cli/hl_adapter.py") is True
    # Order should not matter
    assert is_intentional_pair("cli/hl_adapter.py", "adapters/hl_adapter.py") is True


def test_intentional_pair_non_match():
    assert is_intentional_pair("cli/foo.py", "modules/foo.py") is False


def test_pair_pattern_command_iterator():
    assert matches_pair_pattern(
        "cli/commands/guard.py",
        "cli/daemon/iterators/guard.py",
    ) is True
    # Same in reverse order
    assert matches_pair_pattern(
        "cli/daemon/iterators/guard.py",
        "cli/commands/guard.py",
    ) is True


def test_pair_pattern_command_iterator_different_stems_not_matched():
    assert matches_pair_pattern(
        "cli/commands/guard.py",
        "cli/daemon/iterators/journal.py",
    ) is False


def test_pair_pattern_iterator_module():
    assert matches_pair_pattern(
        "cli/daemon/iterators/heatmap.py",
        "modules/heatmap.py",
    ) is True


def test_pair_pattern_iterator_common():
    assert matches_pair_pattern(
        "cli/daemon/iterators/funding_tracker.py",
        "common/funding_tracker.py",
    ) is True


def test_pair_pattern_iter_suffix():
    assert matches_pair_pattern(
        "cli/daemon/iterators/market_structure_iter.py",
        "common/market_structure.py",
    ) is True


def test_pair_pattern_skill_runners():
    assert matches_pair_pattern(
        "skills/apex/scripts/standalone_runner.py",
        "skills/guard/scripts/standalone_runner.py",
    ) is True
    assert matches_pair_pattern(
        "skills/pulse/scripts/standalone_runner.py",
        "skills/radar/scripts/standalone_runner.py",
    ) is True


def test_pair_pattern_unrelated_paths_not_matched():
    assert matches_pair_pattern(
        "cli/telegram_bot.py",
        "common/models.py",
    ) is False


# ---------- Drift integration ----------

def test_detect_orphans_skips_accepted():
    inventory = {
        "modules": [
            {"name": "cli.research", "path": "cli/research.py"},
            {"name": "orphan_under_review", "path": "some/other_orphan.py"},
        ],
        "edges": [],
    }
    orphans = detect_orphans(inventory, entrypoints=frozenset())
    paths = {o["path"] for o in orphans}
    assert "cli/research.py" not in paths
    assert "some/other_orphan.py" in paths


def test_detect_parallel_tracks_skips_intentional_pair():
    inventory = {
        "modules": [
            {"name": "adapters.hl_adapter", "path": "adapters/hl_adapter.py", "docstring": ""},
            {"name": "cli.hl_adapter", "path": "cli/hl_adapter.py", "docstring": ""},
        ],
    }
    tracks = detect_parallel_tracks(inventory)
    assert tracks == []


def test_detect_parallel_tracks_skips_pattern_match():
    inventory = {
        "modules": [
            {"name": "cli.commands.guard", "path": "cli/commands/guard.py", "docstring": ""},
            {"name": "daemon.iterators.guard", "path": "cli/daemon/iterators/guard.py", "docstring": ""},
        ],
    }
    tracks = detect_parallel_tracks(inventory)
    assert tracks == []


def test_detect_parallel_tracks_still_flags_unrelated():
    inventory = {
        "modules": [
            {"name": "foo.my_module", "path": "foo/my_module.py", "docstring": ""},
            {"name": "bar.my_module", "path": "bar/my_module.py", "docstring": ""},
        ],
    }
    # Same stem, no pattern/intentional exemption — should still flag
    tracks = detect_parallel_tracks(inventory)
    assert len(tracks) == 1
