"""News catalysts feed endpoint."""

from __future__ import annotations

from fastapi import APIRouter

from web.api.dependencies import DATA_DIR
from web.api.readers.jsonl_reader import FileEventReader

router = APIRouter()
_catalysts = FileEventReader(DATA_DIR / "news" / "catalysts.jsonl")


@router.get("/catalysts")
async def get_catalysts(limit: int = 50):
    """Latest catalysts from the news ingest pipeline."""
    return {"catalysts": _catalysts.read_latest(limit)}
