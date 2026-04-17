"""Entry-critic read endpoints for the Dashboard API.

Reads data/research/entry_critiques.jsonl — the append-only record written
by daemon/iterators/entry_critic.py on every new position.

Endpoints:
    GET /api/critiques/?limit=5&market=BRENTOIL
        Returns the most recent ``limit`` critique rows, newest first.
        ``market`` is optional; xyz: prefix is stripped before comparison.

Bearer auth follows the pattern in account.py — depends on the FastAPI
``Request`` object to check ``request.app.state.auth_token``.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Request

# Ensure agent-cli root is on the import path so common.* works in the same
# process as the rest of the API.
_project_root = Path(__file__).resolve().parent.parent.parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from web.api.dependencies import DATA_DIR

router = APIRouter()

_CRITIQUES_PATH = DATA_DIR / "research" / "entry_critiques.jsonl"


def _bare(name: str) -> str:
    """Strip xyz: prefix and uppercase — used for market filter matching."""
    return name.upper().replace("XYZ:", "")


@router.get("/")
async def get_critiques(
    request: Request,
    limit: int = 5,
    market: Optional[str] = None,
):
    """Return the most recent entry critiques, newest first.

    Query params:
        limit  — number of rows to return (1-50, default 5)
        market — optional instrument filter (e.g. BRENTOIL or xyz:BRENTOIL)
    """
    limit = max(1, min(50, limit))
    bare_filter = _bare(market) if market else None

    if not _CRITIQUES_PATH.exists():
        return {"critiques": [], "total": 0, "market_filter": market}

    rows: list[dict] = []
    try:
        with _CRITIQUES_PATH.open("r") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if bare_filter is not None:
                    inst = (row.get("instrument") or "").upper()
                    if _bare(inst) != bare_filter:
                        continue
                rows.append(row)
    except OSError:
        return {"critiques": [], "total": 0, "market_filter": market}

    total = len(rows)
    rows.sort(key=lambda r: r.get("created_at", ""), reverse=True)
    return {
        "critiques": rows[:limit],
        "total": total,
        "market_filter": market,
    }
