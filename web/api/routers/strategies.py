"""Strategy state and decision journal endpoints."""

from __future__ import annotations

import json
from pathlib import Path

from fastapi import APIRouter

from web.api.dependencies import DATA_DIR
from web.api.readers.jsonl_reader import FileEventReader

router = APIRouter()

_STRATEGY_DIR = DATA_DIR / "strategy"
_CONFIG_DIR = DATA_DIR / "config"

_journal = FileEventReader(_STRATEGY_DIR / "oil_botpattern_journal.jsonl")
_adaptive_log = FileEventReader(_STRATEGY_DIR / "oil_botpattern_adaptive_log.jsonl")


def _read_json(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return {}


@router.get("/")
async def list_strategies():
    """Summary of all known strategies."""
    obp_config = _read_json(_CONFIG_DIR / "oil_botpattern.json")
    obp_state = _read_json(_STRATEGY_DIR / "oil_botpattern_state.json")

    enabled = obp_config.get("enabled", False)
    decisions_only = obp_config.get("decisions_only", True)
    short_legs = obp_config.get("short_legs_enabled", False)

    # Sub-systems present in the oil bot pattern strategy
    sub_systems = [
        {"id": 1, "name": "news_ingest", "label": "News Ingest"},
        {"id": 2, "name": "supply_ledger", "label": "Supply Ledger"},
        {"id": 3, "name": "heatmap", "label": "Heatmap"},
        {"id": 4, "name": "bot_classifier", "label": "Bot Classifier"},
        {"id": 5, "name": "oil_botpattern", "label": "Oil Bot Pattern"},
        {"id": 6, "name": "self_tune", "label": "Self-Tune"},
    ]

    sub_system_states = []
    for ss in sub_systems:
        cfg_path = _CONFIG_DIR / f"{ss['name']}.json"
        cfg = _read_json(cfg_path)
        sub_system_states.append({
            "id": ss["id"],
            "name": ss["name"],
            "label": ss["label"],
            "enabled": cfg.get("enabled", True),
            "has_config": cfg_path.exists(),
        })

    # Count brakes tripped
    brakes = {
        "daily": obp_state.get("daily_brake_tripped_at"),
        "weekly": obp_state.get("weekly_brake_tripped_at"),
        "monthly": obp_state.get("monthly_brake_tripped_at"),
    }
    brake_count = sum(1 for v in brakes.values() if v is not None)

    return {
        "strategies": [
            {
                "id": "oil_botpattern",
                "name": "Oil Bot Pattern",
                "enabled": enabled,
                "decisions_only": decisions_only,
                "shadow_mode": decisions_only,
                "short_legs_enabled": short_legs,
                "sub_system_count": len(sub_systems),
                "sub_systems": sub_system_states,
                "brakes_tripped": brake_count,
                "brakes": brakes,
                "instruments": obp_config.get("instruments", []),
            }
        ]
    }


@router.get("/oil-botpattern/state")
async def get_oil_botpattern_state():
    """Current oil bot pattern runtime state."""
    state = _read_json(_STRATEGY_DIR / "oil_botpattern_state.json")
    return {"state": state}


@router.get("/oil-botpattern/journal")
async def get_oil_botpattern_journal(limit: int = 20):
    """Paginated decision journal, newest first."""
    entries = _journal.read_latest(limit)
    return {"journal": entries, "count": len(entries)}


@router.get("/oil-botpattern/config")
async def get_oil_botpattern_config():
    """Strategy config with kill switches."""
    cfg = _read_json(_CONFIG_DIR / "oil_botpattern.json")
    return {"config": cfg}
