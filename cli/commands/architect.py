"""hl architect — self-improvement system.

Detects problems, proposes config fixes, tracks approvals.
ALL MECHANICAL — zero LLM calls. Pure Python pattern matching.

Commands:
    hl architect status    — show pending proposals
    hl architect detect    — scan evaluations for patterns (on-demand)
    hl architect approve   — approve a proposal
    hl architect reject    — reject a proposal
    hl architect history   — show all proposals with outcomes
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from typing import Optional

import typer

architect_app = typer.Typer(no_args_is_help=True)


def _ensure_root():
    root = str(Path(__file__).resolve().parent.parent.parent)
    if root not in sys.path:
        sys.path.insert(0, root)


@architect_app.command("status")
def architect_status(json_output: bool = typer.Option(False, "--json")):
    """Show Architect status — pending proposals, improvement history."""
    _ensure_root()
    from modules.architect_engine import ArchitectEngine

    engine = ArchitectEngine()
    status = engine.status()

    if json_output:
        typer.echo(json.dumps(status, indent=2))
        return

    typer.echo(f"\nArchitect — {status['total_proposals']} total proposals\n")

    by_status = status.get("by_status", {})
    for s, count in by_status.items():
        marker = ">>>" if s == "pending" else "   "
        typer.echo(f"  {marker} {s:<12} {count}")

    pending = status.get("pending", [])
    if pending:
        typer.echo(f"\nPending proposals ({len(pending)}):")
        for p in pending:
            typer.echo(f"\n  ID: {p['id']}")
            typer.echo(f"  Finding: {p['finding']}")
            typer.echo(f"  Change:  {p['change']}")
            typer.echo(f"  Why:     {p['rationale']}")
    else:
        typer.echo("\nNo pending proposals. Run 'hl architect detect' to scan for improvements.")


@architect_app.command("detect")
def architect_detect(json_output: bool = typer.Option(False, "--json")):
    """Scan evaluations for actionable patterns and generate proposals.

    MECHANICAL — zero LLM calls. Reads autoresearch evaluations, judge findings,
    and open issues. Applies pattern-matching rules to generate config change proposals.
    """
    _ensure_root()
    from modules.architect_engine import ArchitectEngine

    engine = ArchitectEngine()
    typer.echo("Scanning evaluations, judge findings, issues...")
    events = engine.tick()

    if json_output:
        typer.echo(json.dumps({"events": events, "status": engine.status()}, indent=2))
        return

    if events:
        typer.echo(f"\n{len(events)} new proposals:")
        for ev in events:
            typer.echo(f"\n  Finding: {ev.get('finding', '?')}")
            typer.echo(f"  Change:  {ev.get('change', '?')}")
            typer.echo(f"  Why:     {ev.get('rationale', '?')}")
    else:
        typer.echo("No new patterns detected.")

    status = engine.status()
    typer.echo(f"\nTotal: {status['total_proposals']} proposals ({status.get('by_status', {})})")


@architect_app.command("approve")
def architect_approve(
    proposal_id: str = typer.Argument(..., help="Proposal ID to approve"),
    notes: str = typer.Option("", "--notes", "-n", help="Reviewer notes"),
):
    """Approve a proposal for implementation."""
    _ensure_root()
    from modules.architect_engine import ArchitectEngine

    engine = ArchitectEngine()
    success = engine.approve_proposal(proposal_id, notes)

    if success:
        typer.echo(f"Approved: {proposal_id}")
        if notes:
            typer.echo(f"Notes: {notes}")
    else:
        typer.echo(f"Error: Proposal '{proposal_id}' not found.", err=True)
        raise typer.Exit(1)


@architect_app.command("reject")
def architect_reject(
    proposal_id: str = typer.Argument(..., help="Proposal ID to reject"),
    notes: str = typer.Option("", "--notes", "-n", help="Reason for rejection"),
):
    """Reject a proposal."""
    _ensure_root()
    from modules.architect_engine import ArchitectEngine

    engine = ArchitectEngine()
    success = engine.reject_proposal(proposal_id, notes)

    if success:
        typer.echo(f"Rejected: {proposal_id}")
    else:
        typer.echo(f"Error: Proposal '{proposal_id}' not found.", err=True)
        raise typer.Exit(1)


@architect_app.command("history")
def architect_history(
    limit: int = typer.Option(20, "--limit", "-l"),
    json_output: bool = typer.Option(False, "--json"),
):
    """Show all proposals with their outcomes."""
    _ensure_root()
    from modules.architect_engine import ArchitectEngine

    engine = ArchitectEngine()
    proposals = engine.proposals[-limit:]

    if json_output:
        typer.echo(json.dumps([p.to_dict() for p in proposals], indent=2))
        return

    if not proposals:
        typer.echo("No proposals yet.")
        return

    typer.echo(f"\n{'ID':<25} {'Status':<10} {'Target':<20} {'Change'}")
    typer.echo("-" * 80)
    for p in proposals:
        hyp = p.hypothesis
        target = hyp.get("target_key", "?")[:18]
        change = f"{hyp.get('current_value', '?')} -> {hyp.get('proposed_value', '?')}"
        typer.echo(f"  {p.proposal_id:<23} {p.status:<10} {target:<20} {change}")
