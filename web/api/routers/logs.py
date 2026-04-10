"""Log streaming (SSE) and history endpoints."""

from __future__ import annotations

import json

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from web.api.dependencies import DATA_DIR
from web.api.readers.log_reader import LogReader

router = APIRouter()
_log_reader = LogReader(DATA_DIR)


@router.get("/sources")
async def get_log_sources():
    """Available log sources."""
    return {"sources": _log_reader.available_sources()}


@router.get("/history")
async def get_log_history(source: str = "daemon", lines: int = 200):
    """Last N lines from a log source."""
    return {"source": source, "lines": _log_reader.tail(source, lines)}


@router.get("/stream")
async def stream_logs(source: str = "daemon"):
    """SSE endpoint — streams new log lines as they appear."""
    async def generate():
        async for entry in _log_reader.stream(source):
            yield f"event: log_line\ndata: {json.dumps(entry)}\n\n"

    return StreamingResponse(generate(), media_type="text/event-stream")
