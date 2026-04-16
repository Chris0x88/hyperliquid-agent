"""Strategy roster — CRUD for active strategies in the daemon."""
from __future__ import annotations

import importlib
import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

from daemon.context import DataRequirements, StrategySlot
from cli.strategy_registry import STRATEGY_REGISTRY, resolve_strategy_path

log = logging.getLogger("daemon.roster")


class Roster:
    """Manages active strategy slots with persistence."""

    def __init__(self, path: str = "data/daemon/roster.json"):
        self._path = Path(path)
        self.slots: Dict[str, StrategySlot] = {}

    # ── CRUD ──────────────────────────────────────────────────

    def add(
        self,
        name: str,
        instrument: str = "BTC-PERP",
        tick_interval: int = 3600,
        params: Optional[Dict[str, Any]] = None,
    ) -> StrategySlot:
        if name in self.slots:
            raise ValueError(f"Strategy '{name}' already in roster")

        strategy_path = resolve_strategy_path(name)
        registry_entry = STRATEGY_REGISTRY.get(name, {})
        merged_params = {**registry_entry.get("params", {}), **(params or {})}

        slot = StrategySlot(
            name=name,
            strategy_path=strategy_path,
            instrument=instrument,
            tick_interval=tick_interval,
            params=merged_params,
            data_reqs=DataRequirements(instruments=[instrument]),
        )
        self.slots[name] = slot
        log.info("Added %s on %s (tick=%ds)", name, instrument, tick_interval)
        return slot

    def remove(self, name: str) -> None:
        if name not in self.slots:
            raise ValueError(f"Strategy '{name}' not in roster")
        del self.slots[name]
        log.info("Removed %s from roster", name)

    def pause(self, name: str) -> None:
        self._get(name).paused = True
        log.info("Paused %s", name)

    def resume(self, name: str) -> None:
        self._get(name).paused = False
        log.info("Resumed %s", name)

    def _get(self, name: str) -> StrategySlot:
        if name not in self.slots:
            raise ValueError(f"Strategy '{name}' not in roster")
        return self.slots[name]

    # ── Instantiation ─────────────────────────────────────────

    def instantiate_all(self) -> None:
        """Import and instantiate strategy classes for all slots."""
        for slot in self.slots.values():
            if slot.strategy is not None:
                continue
            slot.strategy = _load_strategy(slot.strategy_path, slot.params)
            log.info("Instantiated %s (%s)", slot.name, slot.strategy_path)

    # ── Persistence ───────────────────────────────────────────

    def save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        data = []
        for s in self.slots.values():
            data.append({
                "name": s.name,
                "strategy_path": s.strategy_path,
                "instrument": s.instrument,
                "tick_interval": s.tick_interval,
                "last_tick": s.last_tick,
                "paused": s.paused,
                "params": s.params,
            })
        self._path.write_text(json.dumps(data, indent=2))

    def load(self) -> None:
        if not self._path.exists():
            return
        data = json.loads(self._path.read_text())
        for entry in data:
            slot = StrategySlot(
                name=entry["name"],
                strategy_path=entry["strategy_path"],
                instrument=entry["instrument"],
                tick_interval=entry["tick_interval"],
                last_tick=entry.get("last_tick", 0),
                paused=entry.get("paused", False),
                params=entry.get("params", {}),
                data_reqs=DataRequirements(instruments=[entry["instrument"]]),
            )
            self.slots[slot.name] = slot

    def ensure_default(self) -> None:
        """If roster is empty, add the default strategy (paused by default)."""
        if not self.slots:
            self.add("power_law_btc", instrument="BTC-PERP", tick_interval=3600)
            self.pause("power_law_btc")


def _load_strategy(path: str, params: Dict[str, Any]) -> Any:
    """Import module:Class and instantiate with params."""
    module_path, class_name = path.rsplit(":", 1)
    mod = importlib.import_module(module_path)
    cls = getattr(mod, class_name)
    return cls(**params)
