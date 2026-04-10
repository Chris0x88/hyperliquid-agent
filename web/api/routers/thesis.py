"""Thesis state endpoints — read and update conviction per market."""

from __future__ import annotations

import sys
from dataclasses import asdict
from pathlib import Path
from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel

_project_root = Path(__file__).resolve().parent.parent.parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from common.thesis import ThesisState

router = APIRouter()


class ThesisUpdate(BaseModel):
    direction: str | None = None
    conviction: float | None = None
    thesis_summary: str | None = None
    take_profit_price: float | None = None
    invalidation_conditions: list[str] | None = None
    tactical_notes: str | None = None


def _thesis_to_dict(ts: ThesisState) -> dict[str, Any]:
    d = asdict(ts)
    d["age_hours"] = ts.age_hours
    d["needs_review"] = ts.needs_review
    d["is_stale"] = ts.is_stale
    d["effective_conviction"] = ts.effective_conviction()
    return d


@router.get("/")
async def get_all_theses():
    """All thesis states across markets."""
    all_ts = ThesisState.load_all()
    return {
        "theses": {market: _thesis_to_dict(ts) for market, ts in all_ts.items()}
    }


@router.get("/{market}")
async def get_thesis(market: str):
    """Thesis state for a specific market."""
    ts = ThesisState.load(market)
    if not ts:
        return {"error": f"No thesis found for {market}"}
    return _thesis_to_dict(ts)


@router.put("/{market}")
async def update_thesis(market: str, body: ThesisUpdate):
    """Update thesis fields for a market."""
    ts = ThesisState.load(market)
    if not ts:
        return {"error": f"No thesis found for {market}"}

    if body.direction is not None:
        ts.direction = body.direction
    if body.conviction is not None:
        ts.conviction = body.conviction
    if body.thesis_summary is not None:
        ts.thesis_summary = body.thesis_summary
    if body.take_profit_price is not None:
        ts.take_profit_price = body.take_profit_price
    if body.invalidation_conditions is not None:
        ts.invalidation_conditions = body.invalidation_conditions
    if body.tactical_notes is not None:
        ts.tactical_notes = body.tactical_notes

    path = ts.save()
    return {"status": "ok", "path": path, "thesis": _thesis_to_dict(ts)}
