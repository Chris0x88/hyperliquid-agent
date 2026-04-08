"""Tests for drift.detect_parallel_tracks()."""
from __future__ import annotations

from guardian.drift import detect_parallel_tracks


def test_no_parallel_tracks_when_names_distinct():
    inventory = {
        "modules": [
            {"name": "cartographer", "path": "cartographer.py", "docstring": ""},
            {"name": "risk_manager", "path": "risk_manager.py", "docstring": ""},
        ],
    }
    tracks = detect_parallel_tracks(inventory)
    assert tracks == []


def test_detects_similar_module_names():
    inventory = {
        "modules": [
            {"name": "memory_manager", "path": "memory_manager.py", "docstring": "manages memory"},
            {"name": "memory_manager_v2", "path": "memory_manager_v2.py", "docstring": "manages memory better"},
        ],
    }
    tracks = detect_parallel_tracks(inventory, similarity_threshold=0.6)
    assert len(tracks) >= 1
    names = {tuple(sorted([t["a"], t["b"]])) for t in tracks}
    assert ("memory_manager", "memory_manager_v2") in names


def test_ignores_dissimilar_modules():
    inventory = {
        "modules": [
            {"name": "alpha", "path": "alpha.py", "docstring": "alpha module"},
            {"name": "beta", "path": "beta.py", "docstring": "beta module"},
        ],
    }
    tracks = detect_parallel_tracks(inventory, similarity_threshold=0.6)
    assert tracks == []
