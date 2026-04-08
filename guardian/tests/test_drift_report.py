"""Tests for drift.build_drift_report() and write_drift_report()."""
from __future__ import annotations

import json
from pathlib import Path

from guardian.drift import build_drift_report, write_drift_report


def test_build_report_structure():
    inventory = {
        "modules": [{"name": "a", "path": "a.py"}, {"name": "orphan", "path": "orphan.py"}],
        "edges": [],
        "telegram": {
            "handlers": [],
            "handlers_dict_keys": [],
            "menu_commands": [],
            "help_mentions": [],
            "guide_mentions": [],
        },
        "iterators": [],
    }
    report = build_drift_report(inventory, prev_inventory=None)
    assert "orphans" in report
    assert "parallel_tracks" in report
    assert "telegram_gaps" in report
    assert "timestamp" in report
    assert "summary" in report


def test_write_report_creates_json_and_md(tmp_path: Path):
    inventory = {
        "modules": [{"name": "a", "path": "a.py"}],
        "edges": [],
        "telegram": {"handlers": [], "handlers_dict_keys": [], "menu_commands": [], "help_mentions": [], "guide_mentions": []},
        "iterators": [],
    }
    report = build_drift_report(inventory, prev_inventory=None)
    write_drift_report(report, tmp_path)
    assert (tmp_path / "drift_report.json").exists()
    assert (tmp_path / "drift_report.md").exists()
    loaded = json.loads((tmp_path / "drift_report.json").read_text())
    assert loaded["summary"] == report["summary"]


def test_report_counts_p0_findings():
    inventory = {
        "modules": [],
        "edges": [],
        "telegram": {
            "handlers": [{"name": "cmd_orphan"}],
            "handlers_dict_keys": [],
            "menu_commands": [],
            "help_mentions": [],
            "guide_mentions": [],
        },
        "iterators": [],
    }
    report = build_drift_report(inventory, prev_inventory=None)
    assert report["summary"]["p0_count"] >= 1
