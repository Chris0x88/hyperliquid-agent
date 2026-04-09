"""CLI commands for the Architect Engine — mechanical self-improvement.

Usage:
    hl architect status        — show findings and proposal counts
    hl architect detect        — run detection now (pure Python, zero AI)
    hl architect proposals     — list pending proposals
    hl architect approve <id>  — approve a proposal
    hl architect reject <id>   — reject a proposal
    hl architect findings      — show all detected patterns
"""
from __future__ import annotations

import typer

app = typer.Typer(help="Self-improvement engine")


@app.command()
def status():
    """Show findings and proposal summary."""
    from modules.architect_engine import ArchitectEngine
    arch = ArchitectEngine()

    info = arch.get_status()
    typer.echo(f"Architect Engine — {'ENABLED' if info['enabled'] else 'DISABLED'}\n")
    typer.echo(f"  Findings: {info['findings']}")
    for sev, count in info["findings_by_severity"].items():
        if count:
            typer.echo(f"    {sev}: {count}")
    typer.echo(f"\n  Proposals:")
    typer.echo(f"    pending:  {info['proposals_pending']}")
    typer.echo(f"    approved: {info['proposals_approved']}")
    typer.echo(f"    applied:  {info['proposals_applied']}")


@app.command()
def detect():
    """Run detection now (pure Python, zero AI, zero cost)."""
    from modules.architect_engine import ArchitectEngine
    arch = ArchitectEngine()

    if not arch.enabled:
        typer.echo("Architect Engine is DISABLED. Enable in data/config/architect.json")
        return

    findings = arch.detect()
    if findings:
        typer.echo(f"Found {len(findings)} new patterns:\n")
        for f in findings:
            typer.echo(f"  [{f.severity}] {f.pattern_type}: {f.description}")
            typer.echo(f"    Occurrences: {f.occurrences}")

        # Auto-generate proposals
        proposals = arch.hypothesize(findings)
        if proposals:
            typer.echo(f"\nGenerated {len(proposals)} proposals:")
            for p in proposals:
                typer.echo(f"  {p.id}: {p.title}")
    else:
        typer.echo("No new patterns detected.")


@app.command()
def proposals():
    """List pending proposals."""
    from modules.architect_engine import ArchitectEngine
    arch = ArchitectEngine()

    pending = arch.get_pending_proposals()
    if not pending:
        typer.echo("No pending proposals.")
        return

    typer.echo(f"{len(pending)} pending proposals:\n")
    for p in pending:
        typer.echo(f"  {p.id}: {p.title}")
        typer.echo(f"    {p.description[:120]}")
        typer.echo(f"    Expected: {p.expected_impact}")
        typer.echo(f"    Change: {p.proposed_change}")
        typer.echo("")


@app.command()
def approve(proposal_id: str, notes: str = ""):
    """Approve a proposal."""
    from modules.architect_engine import ArchitectEngine
    arch = ArchitectEngine()

    if arch.approve(proposal_id, notes):
        typer.echo(f"Proposal {proposal_id} approved.")
    else:
        typer.echo(f"Proposal {proposal_id} not found or not pending.")


@app.command()
def reject(proposal_id: str, notes: str = ""):
    """Reject a proposal."""
    from modules.architect_engine import ArchitectEngine
    arch = ArchitectEngine()

    if arch.reject(proposal_id, notes):
        typer.echo(f"Proposal {proposal_id} rejected.")
    else:
        typer.echo(f"Proposal {proposal_id} not found or not pending.")


@app.command()
def findings():
    """Show all detected patterns."""
    from modules.architect_engine import ArchitectEngine
    arch = ArchitectEngine()

    arch._load_state()
    if not arch._findings:
        typer.echo("No findings yet. Run 'hl architect detect' to scan.")
        return

    typer.echo(f"{len(arch._findings)} findings:\n")
    for f in arch._findings:
        typer.echo(f"  {f.id} [{f.severity}] {f.pattern_type}")
        typer.echo(f"    {f.description}")
        typer.echo(f"    Occurrences: {f.occurrences}")
        if f.evidence:
            typer.echo(f"    Evidence: {', '.join(f.evidence[:3])}")
        typer.echo("")
