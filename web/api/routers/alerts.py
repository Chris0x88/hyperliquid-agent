"""Alerts & Signals feed endpoints — aggregated from multiple JSONL sources."""

from __future__ import annotations

from fastapi import APIRouter

from web.api.dependencies import DATA_DIR
from web.api.readers.jsonl_reader import FileEventReader

router = APIRouter()

# ── Readers ───────────────────────────────────────────────────────────────────

_challenges = FileEventReader(DATA_DIR / "thesis" / "challenges.jsonl")
_audit = FileEventReader(DATA_DIR / "thesis" / "audit.jsonl")
_disruptions = FileEventReader(DATA_DIR / "supply" / "disruptions.jsonl")
_bot_patterns = FileEventReader(DATA_DIR / "research" / "bot_patterns.jsonl")
_errors = FileEventReader(DATA_DIR / "diagnostics" / "errors.jsonl")
_catalysts = FileEventReader(DATA_DIR / "news" / "catalysts.jsonl")
_zones = FileEventReader(DATA_DIR / "heatmap" / "zones.jsonl")
_journal = FileEventReader(DATA_DIR / "strategy" / "journal.jsonl")


# ── Normalisation helpers ─────────────────────────────────────────────────────

def _ts(entry: dict) -> str:
    """Return the best available ISO timestamp from an entry."""
    for key in ("created_at", "timestamp", "decided_at", "ts", "detected_at"):
        v = entry.get(key)
        if v:
            return str(v)
    return ""


def _normalise_challenge(e: dict) -> dict:
    return {
        "id": e.get("id", ""),
        "type": "thesis_challenge",
        "severity": "high",
        "market": e.get("thesis_market", ""),
        "summary": e.get("invalidation_condition", "Thesis invalidation check"),
        "detail": e.get("matched_headline", ""),
        "source": "thesis_challenger",
        "timestamp": _ts(e),
        "raw": e,
    }


def _normalise_audit(e: dict) -> dict:
    conviction = e.get("conviction") or e.get("new_conviction")
    summary = e.get("summary") or e.get("reason") or "Conviction adjustment"
    return {
        "id": e.get("id", ""),
        "type": "conviction_change",
        "severity": "medium",
        "market": e.get("market", ""),
        "summary": summary,
        "detail": f"Conviction: {conviction}" if conviction is not None else "",
        "source": "conviction_engine",
        "timestamp": _ts(e),
        "raw": e,
    }


def _normalise_disruption(e: dict) -> dict:
    severity_raw = str(e.get("severity", "medium")).lower()
    severity = severity_raw if severity_raw in ("critical", "high", "medium", "low") else "medium"
    return {
        "id": e.get("id", ""),
        "type": "supply_disruption",
        "severity": severity,
        "market": e.get("market") or e.get("instrument", ""),
        "summary": e.get("headline") or e.get("summary") or e.get("description", "Supply disruption"),
        "detail": e.get("details") or e.get("notes", ""),
        "source": "supply_monitor",
        "timestamp": _ts(e),
        "raw": e,
    }


def _normalise_bot_pattern(e: dict) -> dict:
    return {
        "id": e.get("id", ""),
        "type": "bot_pattern",
        "severity": "medium",
        "market": e.get("market") or e.get("instrument", ""),
        "summary": e.get("classification") or e.get("pattern_type") or "Bot-driven move detected",
        "detail": e.get("notes") or e.get("description", ""),
        "source": "bot_classifier",
        "timestamp": _ts(e),
        "raw": e,
    }


def _normalise_error(e: dict) -> dict:
    level = str(e.get("level", "error")).lower()
    severity = "critical" if level in ("critical", "fatal") else "high"
    return {
        "id": e.get("id", ""),
        "type": "system_error",
        "severity": severity,
        "market": "",
        "summary": e.get("message") or e.get("error") or "System error",
        "detail": e.get("traceback") or e.get("detail", ""),
        "source": e.get("source") or e.get("component", "daemon"),
        "timestamp": _ts(e),
        "raw": e,
    }


def _normalise_catalyst(e: dict) -> dict:
    severity_raw = str(e.get("severity", "medium")).lower()
    severity = severity_raw if severity_raw in ("critical", "high", "medium", "low") else "medium"
    return {
        "id": e.get("id", ""),
        "type": "catalyst",
        "severity": severity,
        "market": e.get("market") or e.get("instrument", ""),
        "summary": e.get("headline") or e.get("title") or "News catalyst",
        "detail": e.get("summary") or e.get("body", ""),
        "source": "news_ingest",
        "timestamp": _ts(e),
        "raw": e,
    }


def _normalise_zone(e: dict) -> dict:
    return {
        "id": e.get("id", ""),
        "type": "heatmap_zone",
        "severity": "low",
        "market": e.get("market") or e.get("instrument", ""),
        "summary": e.get("label") or e.get("zone_type") or "Liquidity zone snapshot",
        "detail": e.get("notes") or "",
        "source": "heatmap",
        "timestamp": _ts(e),
        "raw": e,
    }


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("/")
async def get_alerts(limit: int = 50):
    """Unified alert feed — newest-first across all sources."""
    combined: list[dict] = []

    for entry in _challenges.read_latest(limit):
        combined.append(_normalise_challenge(entry))
    for entry in _audit.read_latest(limit):
        combined.append(_normalise_audit(entry))
    for entry in _disruptions.read_latest(limit):
        combined.append(_normalise_disruption(entry))
    for entry in _bot_patterns.read_latest(limit):
        combined.append(_normalise_bot_pattern(entry))
    for entry in _errors.read_latest(limit):
        combined.append(_normalise_error(entry))
    for entry in _catalysts.read_latest(limit):
        combined.append(_normalise_catalyst(entry))
    for entry in _zones.read_latest(limit):
        combined.append(_normalise_zone(entry))

    # Sort newest-first by timestamp string (ISO sorts lexicographically)
    combined.sort(key=lambda x: x["timestamp"], reverse=True)

    return {"alerts": combined[:limit]}


@router.get("/signals")
async def get_signals(limit: int = 30):
    """Bot-pattern signals and heatmap zone updates."""
    signals: list[dict] = []
    for entry in _bot_patterns.read_latest(limit):
        signals.append(_normalise_bot_pattern(entry))
    for entry in _zones.read_latest(limit):
        signals.append(_normalise_zone(entry))
    signals.sort(key=lambda x: x["timestamp"], reverse=True)
    return {"signals": signals[:limit]}


@router.get("/errors")
async def get_errors(limit: int = 20):
    """Recent system errors from the diagnostics log."""
    errors = [_normalise_error(e) for e in _errors.read_latest(limit)]
    return {"errors": errors}


@router.get("/thesis-challenges")
async def get_thesis_challenges(limit: int = 20):
    """Thesis invalidation events."""
    challenges = [_normalise_challenge(e) for e in _challenges.read_latest(limit)]
    return {"challenges": challenges}


@router.get("/disruptions")
async def get_disruptions(limit: int = 20):
    """Supply disruption events."""
    disruptions = [_normalise_disruption(e) for e in _disruptions.read_latest(limit)]
    return {"disruptions": disruptions}
