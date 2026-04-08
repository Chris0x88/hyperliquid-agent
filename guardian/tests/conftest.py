"""Shared pytest fixtures for Guardian tests."""
from __future__ import annotations

from pathlib import Path
from typing import Iterator

import pytest


@pytest.fixture
def tmp_repo(tmp_path: Path) -> Iterator[Path]:
    """Provide a minimal fake repo layout for Guardian tests."""
    (tmp_path / "cli").mkdir()
    (tmp_path / "cli" / "daemon").mkdir()
    (tmp_path / "cli" / "daemon" / "iterators").mkdir()
    (tmp_path / "docs" / "plans").mkdir(parents=True)
    (tmp_path / "docs" / "wiki" / "decisions").mkdir(parents=True)
    (tmp_path / "guardian" / "state").mkdir(parents=True)
    yield tmp_path


@pytest.fixture
def write_file():
    """Helper to write a file and return its path."""
    def _write(path: Path, content: str) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
        return path
    return _write
