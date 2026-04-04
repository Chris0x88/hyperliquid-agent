"""Asset authority system — controls who manages each position.

Three authority levels:
- ``agent``: Bot manages entries, exits, sizing, dip-adds, profit-takes.
           User gets reports. Bot acts on conviction engine + thesis.
- ``manual``: User trades. Bot is safety-net only — ensures SL/TP exist,
            alerts on dangerous leverage. Never enters or exits.
- ``off``: Not watched at all. No alerts, no stops, nothing.

Default for any unregistered asset is ``manual`` (safe default).

Storage: data/authority.json
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

log = logging.getLogger("authority")

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_AUTHORITY_FILE = _PROJECT_ROOT / "data" / "authority.json"

VALID_LEVELS = ("agent", "manual", "off")
DEFAULT_LEVEL = "manual"


def _load() -> dict:
    """Load authority config from disk."""
    if _AUTHORITY_FILE.exists():
        try:
            return json.loads(_AUTHORITY_FILE.read_text())
        except (json.JSONDecodeError, OSError):
            log.warning("Corrupted authority.json, using defaults")
    return {"assets": {}, "default": DEFAULT_LEVEL}


def _save(data: dict) -> None:
    """Write authority config to disk."""
    _AUTHORITY_FILE.parent.mkdir(parents=True, exist_ok=True)
    _AUTHORITY_FILE.write_text(json.dumps(data, indent=2) + "\n")


def get_authority(asset: str) -> str:
    """Get authority level for an asset. Returns 'manual' if not set."""
    data = _load()
    entry = data.get("assets", {}).get(asset, {})
    if isinstance(entry, dict):
        return entry.get("authority", data.get("default", DEFAULT_LEVEL))
    return data.get("default", DEFAULT_LEVEL)


def get_all() -> dict:
    """Return all asset authority entries."""
    return _load().get("assets", {})


def delegate(asset: str, note: str = "") -> str:
    """Set asset authority to 'agent'. Returns confirmation message."""
    return set_authority(asset, "agent", note)


def reclaim(asset: str, note: str = "") -> str:
    """Set asset authority to 'manual'. Returns confirmation message."""
    return set_authority(asset, "manual", note)


def set_authority(asset: str, level: str, note: str = "") -> str:
    """Set authority level for an asset."""
    level = level.lower().strip()
    if level not in VALID_LEVELS:
        return f"Invalid authority level '{level}'. Must be one of: {', '.join(VALID_LEVELS)}"

    data = _load()
    assets = data.setdefault("assets", {})
    old_entry = assets.get(asset, {})
    old_level = old_entry.get("authority", DEFAULT_LEVEL) if isinstance(old_entry, dict) else DEFAULT_LEVEL

    assets[asset] = {
        "authority": level,
        "changed_at": datetime.now(timezone.utc).isoformat(),
        "note": note,
    }
    _save(data)

    log.info("Authority changed: %s %s → %s", asset, old_level, level)
    return f"{asset}: {old_level} → {level}"


def is_agent_managed(asset: str) -> bool:
    """Check if the bot has authority to trade this asset."""
    return get_authority(asset) == "agent"


def is_watched(asset: str) -> bool:
    """Check if the asset should be monitored at all (not 'off')."""
    return get_authority(asset) != "off"


def format_authority_status(positions: Optional[list] = None) -> str:
    """Format authority status for Telegram display.

    If positions are provided, shows authority alongside each position.
    """
    data = _load()
    assets = data.get("assets", {})

    lines = ["*Asset Authority*\n"]

    # Show configured assets
    level_icons = {"agent": "🤖", "manual": "👤", "off": "⬛"}

    if not assets and not positions:
        lines.append("No assets configured.")
        lines.append("\nUse `/delegate ASSET` to hand an asset to the agent")
        lines.append("Use `/reclaim ASSET` to take it back")
        return "\n".join(lines)

    # Show positions first (most relevant)
    shown = set()
    if positions:
        lines.append("*Active Positions:*")
        for pos in positions:
            coin = pos.get("coin", "?")
            side = pos.get("side", "long")
            size = pos.get("size", 0)
            entry = pos.get("entry_price", 0)
            level = get_authority(coin)
            icon = level_icons.get(level, "❓")
            dot = "🟢" if side == "long" else "🔴"
            lines.append(f"{dot} `{coin}` {side} {size} @ `${entry:,.2f}` — {icon} {level}")
            shown.add(coin)

    # Show configured assets not in positions
    other = {k: v for k, v in assets.items() if k not in shown}
    if other:
        lines.append("\n*Configured (no position):*")
        for asset, entry in other.items():
            level = entry.get("authority", DEFAULT_LEVEL)
            icon = level_icons.get(level, "❓")
            lines.append(f"{icon} `{asset}` — {level}")

    lines.append(f"\nDefault: `{data.get('default', DEFAULT_LEVEL)}`")
    lines.append("\n`/delegate ASSET` — hand to agent")
    lines.append("`/reclaim ASSET` — take back")
    return "\n".join(lines)
