"""Daemon state, iterators, tier control."""

from __future__ import annotations

import ast
import json
import os
import signal
import sys
from pathlib import Path

from fastapi import APIRouter
from pydantic import BaseModel

_project_root = Path(__file__).resolve().parent.parent.parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from daemon.tiers import TIER_ITERATORS, VALID_TIERS
from web.api.dependencies import DATA_DIR
from web.api.iterator_descriptions import ITERATOR_DESCRIPTIONS, CATEGORY_FALLBACK

router = APIRouter()

_ITERATORS_DIR = _project_root / "daemon" / "iterators"


def _extract_docstring(name: str) -> tuple[str | None, str | None]:
    """Parse the module-level docstring from daemon/iterators/<name>.py.

    Returns (first_sentence_or_line, full_docstring) — both None if missing.
    """
    # Handle the market_structure alias
    candidates = [name, name.replace("market_structure", "market_structure_iter")]
    for candidate in candidates:
        src = _ITERATORS_DIR / f"{candidate}.py"
        if src.exists():
            try:
                tree = ast.parse(src.read_text(encoding="utf-8"))
                doc = ast.get_docstring(tree)
                if doc:
                    # First sentence = everything up to first newline or period+space
                    first_line = doc.split("\n")[0].strip()
                    # Strip trailing — separator if present
                    if " — " in first_line:
                        first_line = first_line
                    elif "." in first_line:
                        first_line = first_line.split(".")[0].strip() + "."
                    return first_line, doc
            except (SyntaxError, OSError):
                pass
    return None, None


def _get_iterator_meta(name: str) -> dict:
    """Build rich metadata for one iterator.

    Priority: ITERATOR_DESCRIPTIONS (hand-curated) → docstring auto-extraction.
    """
    # Resolve config and source paths
    config_path = f"data/config/{name}.json"
    # Handle market_structure alias
    src_name = "market_structure_iter" if name == "market_structure" else name
    source_file = f"daemon/iterators/{src_name}.py"
    has_source = (_project_root / source_file).exists()

    # Which tiers include this iterator
    tier_set = [t for t in VALID_TIERS if name in TIER_ITERATORS.get(t, [])]

    # Config _comment field
    cfg_comment: str | None = None
    cfg_full = DATA_DIR / "config" / f"{name}.json"
    if cfg_full.exists():
        try:
            raw = json.loads(cfg_full.read_text(encoding="utf-8"))
            cfg_comment = raw.get("_comment") or raw.get("comment")
        except (json.JSONDecodeError, OSError):
            pass

    # Hand-curated override takes priority
    if name in ITERATOR_DESCRIPTIONS:
        curated = ITERATOR_DESCRIPTIONS[name]
        return {
            "description": curated.get("description"),
            "purpose": curated.get("purpose"),
            "kill_switch_impact": curated.get("kill_switch_impact"),
            "inputs": curated.get("inputs", []),
            "outputs": curated.get("outputs", []),
            "category": curated.get("category", CATEGORY_FALLBACK.get(name, "Operations")),
            "tier_set": tier_set,
            "config_path": config_path,
            "source_file": source_file if has_source else None,
        }

    # Auto-extract from docstring
    first_line, full_doc = _extract_docstring(name)

    # Merge config _comment into purpose if no docstring
    purpose = full_doc or cfg_comment

    return {
        "description": first_line,
        "purpose": purpose,
        "kill_switch_impact": None,
        "inputs": [],
        "outputs": [],
        "category": CATEGORY_FALLBACK.get(name, "Operations"),
        "tier_set": tier_set,
        "config_path": config_path,
        "source_file": source_file if has_source else None,
    }


class TierUpdate(BaseModel):
    tier: str


class IteratorToggle(BaseModel):
    enabled: bool


@router.get("/state")
async def get_daemon_state():
    """Daemon state: tier, tick count, PID."""
    state_path = DATA_DIR / "daemon" / "state.json"
    pid_path = DATA_DIR / "daemon" / "daemon.pid"

    state = {}
    if state_path.exists():
        try:
            state = json.loads(state_path.read_text())
        except (json.JSONDecodeError, OSError):
            pass

    pid_alive = False
    pid = None
    if pid_path.exists():
        try:
            pid = int(pid_path.read_text().strip())
            os.kill(pid, 0)
            pid_alive = True
        except (ValueError, OSError):
            pass

    return {
        **state,
        "pid": pid,
        "pid_alive": pid_alive,
    }


@router.get("/iterators")
async def get_iterators():
    """List all iterators with tier membership, enabled state, and rich descriptions."""
    config_dir = DATA_DIR / "config"
    iterators = []

    # Collect all unique iterator names
    all_names: set[str] = set()
    for tier_list in TIER_ITERATORS.values():
        all_names.update(tier_list)

    for name in sorted(all_names):
        # Determine which tiers include this iterator
        tiers = [t for t in VALID_TIERS if name in TIER_ITERATORS.get(t, [])]

        # Check config for enabled state
        config_path = config_dir / f"{name}.json"
        enabled = True
        if config_path.exists():
            try:
                cfg = json.loads(config_path.read_text())
                enabled = cfg.get("enabled", True)
            except (json.JSONDecodeError, OSError):
                pass

        meta = _get_iterator_meta(name)

        iterators.append({
            "name": name,
            "tiers": tiers,
            "enabled": enabled,
            "has_config": config_path.exists(),
            # Rich description fields
            "description": meta["description"],
            "purpose": meta["purpose"],
            "kill_switch_impact": meta["kill_switch_impact"],
            "inputs": meta["inputs"],
            "outputs": meta["outputs"],
            "category": meta["category"],
            "tier_set": meta["tier_set"],
            "config_path": meta["config_path"],
            "source_file": meta["source_file"],
        })

    return {"iterators": iterators, "valid_tiers": VALID_TIERS}


@router.put("/iterators/{name}")
async def toggle_iterator(name: str, body: IteratorToggle):
    """Toggle an iterator's enabled state in its config file."""
    config_path = DATA_DIR / "config" / f"{name}.json"

    if config_path.exists():
        try:
            cfg = json.loads(config_path.read_text())
        except (json.JSONDecodeError, OSError):
            cfg = {}
    else:
        cfg = {}

    cfg["enabled"] = body.enabled

    tmp = config_path.with_suffix(".tmp")
    tmp.write_text(json.dumps(cfg, indent=2))
    tmp.replace(config_path)

    return {"name": name, "enabled": body.enabled}


@router.get("/tier")
async def get_tier():
    """Current daemon tier."""
    state_path = DATA_DIR / "daemon" / "state.json"
    if state_path.exists():
        try:
            state = json.loads(state_path.read_text())
            return {"tier": state.get("tier", "watch")}
        except (json.JSONDecodeError, OSError):
            pass
    return {"tier": "watch"}


@router.post("/restart")
async def restart_daemon():
    """Send SIGTERM to daemon PID for graceful restart (launchd will respawn)."""
    pid_path = DATA_DIR / "daemon" / "daemon.pid"
    if not pid_path.exists():
        return {"status": "error", "message": "No daemon PID file found"}

    try:
        pid = int(pid_path.read_text().strip())
        os.kill(pid, signal.SIGTERM)
        return {"status": "ok", "message": f"SIGTERM sent to PID {pid}"}
    except (ValueError, OSError) as e:
        return {"status": "error", "message": str(e)}
