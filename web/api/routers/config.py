"""Config file management endpoints."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Any

from web.api.dependencies import DATA_DIR
from web.api.readers.config_reader import FileConfigReader

router = APIRouter()
_reader = FileConfigReader(DATA_DIR / "config")


class ConfigUpdate(BaseModel):
    data: dict[str, Any]


@router.get("/")
async def list_configs():
    """List all config files with metadata."""
    return {"configs": _reader.list_configs()}


@router.get("/{filename}")
async def get_config(filename: str):
    """Read a specific config file."""
    result = _reader.read_config(filename)
    if "error" in result:
        raise HTTPException(status_code=404, detail=result["error"])
    return {"filename": filename, "data": result}


@router.put("/{filename}")
async def update_config(filename: str, body: ConfigUpdate):
    """Update a config file (creates .bak backup)."""
    # Validate the filename is safe
    if "/" in filename or "\\" in filename or ".." in filename:
        raise HTTPException(status_code=400, detail="Invalid filename")
    if not filename.endswith((".json", ".yaml", ".yml")):
        raise HTTPException(status_code=400, detail="Only JSON/YAML configs supported")

    try:
        _reader.write_config(filename, body.data)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    return {"status": "ok", "filename": filename}
