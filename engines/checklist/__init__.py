"""Market Checklist Framework — Phase 2 of the master plan.

Deterministic, zero-LLM safety checks run before sleep (evening) and
on wake (morning). Each check returns a structured verdict so Telegram
commands can render a pass/warn/fail cockpit view.

Usage:
    from engines.checklist.runner import run_checklist

    result = run_checklist("xyz:SILVER", mode="evening", ctx=ctx)
    # result = {"market": ..., "mode": ..., "items": [...], "summary": {...}}

See spec.py for the full dataclass contract.
"""
from engines.checklist.spec import ChecklistItem, ChecklistResult, MarketChecklist

__all__ = ["ChecklistItem", "ChecklistResult", "MarketChecklist"]
