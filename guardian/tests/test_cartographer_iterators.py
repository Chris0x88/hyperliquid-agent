"""Tests for cartographer's daemon iterator scanning."""
from __future__ import annotations

from pathlib import Path

from guardian.cartographer import scan_iterators

FIXTURE = Path(__file__).parent / "fixtures" / "fake_iterators"


def test_scan_finds_iterator_modules():
    result = scan_iterators(FIXTURE)
    names = {i["module"] for i in result}
    assert "heartbeat" in names


def test_scan_extracts_iterator_class_name():
    result = scan_iterators(FIXTURE)
    assert any(i["class"] == "HeartbeatIterator" for i in result)
