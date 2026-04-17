"""News catalysts feed endpoints."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from web.api.auth import verify_token
from web.api.dependencies import DATA_DIR
from web.api.readers.jsonl_reader import FileEventReader

router = APIRouter()
_catalysts = FileEventReader(DATA_DIR / "news" / "catalysts.jsonl")

_HEADLINES_PATH = DATA_DIR / "news" / "headlines.jsonl"
_THESIS_DIR = DATA_DIR / "thesis"

# ── helpers ──────────────────────────────────────────────────────────────────


def _read_jsonl_all(path: Path) -> list[dict[str, Any]]:
    """Read every line from a JSONL file; return [] if missing."""
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    try:
        with open(path) as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        rows.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue
    except OSError:
        pass
    return rows


def _build_headline_index() -> dict[str, dict[str, Any]]:
    """Index headlines.jsonl by id."""
    return {row["id"]: row for row in _read_jsonl_all(_HEADLINES_PATH) if "id" in row}


def _build_catalyst_index() -> dict[str, dict[str, Any]]:
    """Index catalysts.jsonl by id."""
    return {
        row["id"]: row
        for row in _read_jsonl_all(DATA_DIR / "news" / "catalysts.jsonl")
        if "id" in row
    }


def _load_theses() -> list[dict[str, Any]]:
    """Load all thesis JSON files from data/thesis/."""
    theses: list[dict[str, Any]] = []
    if not _THESIS_DIR.exists():
        return theses
    for p in _THESIS_DIR.glob("*_state.json"):
        try:
            data = json.loads(p.read_text())
            data["_file"] = p.name
            theses.append(data)
        except Exception:
            continue
    return theses


def _coin_matches(instrument: str, market_field: str) -> bool:
    """Match instrument against thesis market, handling xyz: prefix variants."""
    inst_clean = instrument.replace("xyz:", "").upper()
    mkt_clean = market_field.replace("xyz:", "").upper()
    return inst_clean == mkt_clean


def _linked_theses(instruments: list[str]) -> list[dict[str, Any]]:
    """Return thesis summary rows whose market matches any instrument."""
    if not instruments:
        return []
    theses = _load_theses()
    linked: list[dict[str, Any]] = []
    for ts in theses:
        market = ts.get("market", "")
        if any(_coin_matches(inst, market) for inst in instruments):
            linked.append(
                {
                    "market": market,
                    "direction": ts.get("direction", ""),
                    "conviction": ts.get("conviction", 0.0),
                    "thesis_summary": ts.get("thesis_summary", ""),
                    "invalidation_conditions": ts.get("invalidation_conditions", []),
                }
            )
    return linked


def _audit_rows_for(catalyst_id: str) -> list[dict[str, Any]]:
    """Return audit.jsonl rows whose catalyst_id matches (graceful if missing)."""
    audit_path = _THESIS_DIR / "audit.jsonl"
    rows = _read_jsonl_all(audit_path)
    return [
        r
        for r in rows
        if r.get("catalyst_id") == catalyst_id or r.get("id") == catalyst_id
    ]


# ── endpoints ─────────────────────────────────────────────────────────────────


@router.get("/catalysts")
async def get_catalysts(limit: int = 50):
    """Latest catalysts from the news ingest pipeline."""
    return {"catalysts": _catalysts.read_latest(limit)}


@router.get("/catalyst/{catalyst_id}", dependencies=[Depends(verify_token)])
async def get_catalyst_detail(catalyst_id: str):
    """
    Detail view for a single catalyst.

    Returns:
    - catalyst row
    - joined headline (by headline_id)
    - linked theses (instruments intersection)
    - conviction-adjustment audit rows
    """
    catalyst_index = _build_catalyst_index()
    catalyst = catalyst_index.get(catalyst_id)
    if not catalyst:
        raise HTTPException(
            status_code=404, detail=f"Catalyst {catalyst_id!r} not found"
        )

    headline_id = catalyst.get("headline_id")
    headline_index = _build_headline_index()
    headline = headline_index.get(headline_id) if headline_id else None

    instruments: list[str] = catalyst.get("instruments") or []
    linked = _linked_theses(instruments)
    audit = _audit_rows_for(catalyst_id)

    return {
        "catalyst": catalyst,
        "headline": headline,
        "linked_theses": linked,
        "audit_rows": audit,
        "headline_missing": headline is None and bool(headline_id),
    }
