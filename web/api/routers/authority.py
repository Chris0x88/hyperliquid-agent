"""Per-asset authority delegation endpoints."""

from __future__ import annotations

import sys
from pathlib import Path

from fastapi import APIRouter
from pydantic import BaseModel

_project_root = Path(__file__).resolve().parent.parent.parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from common.authority import get_all, set_authority

router = APIRouter()


class AuthorityUpdate(BaseModel):
    level: str  # "agent" | "manual" | "off"
    note: str = ""


@router.get("/")
async def get_authority_all():
    """All asset authority levels."""
    return {"authority": get_all()}


@router.put("/{asset}")
async def update_authority(asset: str, body: AuthorityUpdate):
    """Set authority level for an asset."""
    msg = set_authority(asset, body.level, body.note)
    return {"status": "ok", "message": msg}
