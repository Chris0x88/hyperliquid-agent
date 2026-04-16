"""Catalyst → CatalystEvent conversion bridge.

Keeps modules/news_engine.py pure by pushing the daemon-type coupling here.
Also handles persistence to data/daemon/external_catalyst_events.json, the file
the existing CatalystDeleverageIterator watches via its new additive reader.
"""
from __future__ import annotations

import json
import logging
from dataclasses import asdict
from pathlib import Path
from typing import Iterable

from daemon.iterators.catalyst_deleverage import CatalystEvent
from engines.learning.news_engine import Catalyst

log = logging.getLogger("catalyst_bridge")


def catalyst_to_events(cat: Catalyst, pre_event_hours: int = 24) -> list[CatalystEvent]:
    """Fan a multi-instrument Catalyst out to one CatalystEvent per instrument."""
    return [
        CatalystEvent(
            name=f"{cat.id}-{instrument}",
            instrument=instrument,
            event_date=cat.event_date.date().isoformat(),
            pre_event_hours=pre_event_hours,
            reduce_leverage_to=None,
            reduce_size_pct=0.25,  # sensible default: 25% size-down ahead of catalyst
            post_event_hours=12,
            executed=False,
        )
        for instrument in cat.instruments
    ]


def persist(
    catalysts: Iterable[Catalyst],
    output_path: str,
    severity_floor: int,
) -> int:
    """Append Catalyst fan-outs above the severity floor to output_path JSON.

    File format: a JSON object {"events": [<CatalystEvent>, ...]}. On first call
    the file is created; on subsequent calls existing events are preserved and
    new events are deduped by `name`.

    Returns the number of new events added.
    """
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    existing: list[dict] = []
    if path.exists():
        try:
            existing = json.loads(path.read_text()).get("events", [])
        except json.JSONDecodeError:
            log.warning("external catalyst file %s corrupt — starting fresh", path)
            existing = []

    existing_names = {e["name"] for e in existing}
    added = 0
    for cat in catalysts:
        if cat.severity < severity_floor:
            continue
        for event in catalyst_to_events(cat):
            if event.name in existing_names:
                continue
            existing.append(asdict(event))
            existing_names.add(event.name)
            added += 1

    path.write_text(json.dumps({"events": existing}, indent=2, default=str))
    return added
