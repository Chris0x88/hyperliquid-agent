"""Watchlist management endpoints."""

from __future__ import annotations

import sys
from pathlib import Path

from fastapi import APIRouter
from pydantic import BaseModel

_project_root = Path(__file__).resolve().parent.parent.parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from common.watchlist import load_watchlist, add_market, remove_market

router = APIRouter()


class MarketAdd(BaseModel):
    display: str
    coin: str
    aliases: list[str] = []
    category: str = "other"


@router.get("/")
async def get_watchlist():
    """Current watchlist."""
    return {"markets": load_watchlist()}


@router.post("/add")
async def watchlist_add(body: MarketAdd):
    """Add a market to the watchlist."""
    ok = add_market(body.display, body.coin, body.aliases, body.category)
    return {"added": ok, "coin": body.coin}


@router.post("/remove/{coin}")
async def watchlist_remove(coin: str):
    """Remove a market from the watchlist."""
    ok = remove_market(coin)
    return {"removed": ok, "coin": coin}
