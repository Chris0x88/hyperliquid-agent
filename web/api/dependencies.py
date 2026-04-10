"""Shared dependencies for the FastAPI backend."""

from __future__ import annotations

from pathlib import Path

# Project root: agent-cli/
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DATA_DIR = PROJECT_ROOT / "data"
STATE_DIR = PROJECT_ROOT / "state"


def get_data_dir() -> Path:
    return DATA_DIR


def get_state_dir() -> Path:
    return STATE_DIR


def get_project_root() -> Path:
    return PROJECT_ROOT
