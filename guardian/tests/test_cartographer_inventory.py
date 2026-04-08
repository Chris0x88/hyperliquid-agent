"""Tests for cartographer's full inventory builder."""
from __future__ import annotations

import json
from pathlib import Path

from guardian.cartographer import build_inventory, write_inventory


def test_build_inventory_on_empty_repo(tmp_repo: Path):
    inv = build_inventory(tmp_repo)
    assert "modules" in inv
    assert "edges" in inv
    assert "telegram" in inv
    assert "iterators" in inv
    assert "timestamp" in inv


def test_write_inventory_creates_json(tmp_repo: Path):
    inv = build_inventory(tmp_repo)
    out_dir = tmp_repo / "guardian" / "state"
    write_inventory(inv, out_dir)
    assert (out_dir / "inventory.json").exists()
    loaded = json.loads((out_dir / "inventory.json").read_text())
    assert loaded["modules"] == inv["modules"]


def test_write_inventory_creates_mermaid(tmp_repo: Path):
    inv = build_inventory(tmp_repo)
    out_dir = tmp_repo / "guardian" / "state"
    write_inventory(inv, out_dir)
    mmd = (out_dir / "map.mmd").read_text()
    assert mmd.startswith("graph")


def test_write_inventory_rotates_previous(tmp_repo: Path):
    out_dir = tmp_repo / "guardian" / "state"
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "inventory.json").write_text('{"modules": [], "edges": [], "timestamp": "old"}')
    inv = build_inventory(tmp_repo)
    write_inventory(inv, out_dir)
    assert (out_dir / "inventory.prev.json").exists()
    prev = json.loads((out_dir / "inventory.prev.json").read_text())
    assert prev["timestamp"] == "old"
