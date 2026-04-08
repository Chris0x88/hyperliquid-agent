"""Tests for cartographer's Python import scanning."""
from __future__ import annotations

from pathlib import Path

from guardian.cartographer import scan_python_imports


FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "mini_repo"


def test_scan_finds_all_python_files():
    result = scan_python_imports(FIXTURE_ROOT)
    modules = {m["name"] for m in result["modules"]}
    assert modules == {"a", "b", "c"}


def test_scan_captures_edges():
    result = scan_python_imports(FIXTURE_ROOT)
    edges = {(e["from"], e["to"]) for e in result["edges"]}
    assert ("a", "b") in edges
    assert ("b", "c") in edges


def test_scan_reports_leaf_as_no_outgoing_edges():
    result = scan_python_imports(FIXTURE_ROOT)
    c_outgoing = [e for e in result["edges"] if e["from"] == "c"]
    assert c_outgoing == []


def test_scan_reports_orphan_candidates():
    result = scan_python_imports(FIXTURE_ROOT)
    inbound = {m["name"]: 0 for m in result["modules"]}
    for e in result["edges"]:
        inbound[e["to"]] = inbound.get(e["to"], 0) + 1
    assert inbound["a"] == 0
    assert inbound["b"] == 1
    assert inbound["c"] == 1
