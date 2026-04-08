"""Tests for drift.detect_orphans()."""
from __future__ import annotations

from guardian.drift import detect_orphans


def test_no_orphans_when_all_modules_imported():
    inventory = {
        "modules": [{"name": "a", "path": "a.py"}, {"name": "b", "path": "b.py"}],
        "edges": [{"from": "a", "to": "b", "kind": "import"}],
    }
    # 'a' is the entrypoint, 'b' is imported by 'a'
    # Only 'b' has inbound edges; 'a' has zero inbound but is the entry.
    # detect_orphans returns modules with zero inbound AND not in entrypoint list.
    orphans = detect_orphans(inventory, entrypoints={"a"})
    assert orphans == []


def test_finds_orphan_with_no_inbound():
    inventory = {
        "modules": [
            {"name": "a", "path": "a.py"},
            {"name": "b", "path": "b.py"},
            {"name": "orphan", "path": "orphan.py"},
        ],
        "edges": [{"from": "a", "to": "b", "kind": "import"}],
    }
    orphans = detect_orphans(inventory, entrypoints={"a"})
    orphan_names = {o["name"] for o in orphans}
    assert "orphan" in orphan_names
    assert "a" not in orphan_names  # entrypoint
    assert "b" not in orphan_names  # imported
