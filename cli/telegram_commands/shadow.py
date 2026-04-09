"""Sub-system 6 L4 shadow counterfactual eval Telegram command.

Part of the incremental telegram_bot.py monolith split. L4 runs
counterfactual replays of approved L2 structural proposals — "what
would have happened if the proposed params had been in effect over the
last N days of trades?" — and writes ShadowEval records.

One deterministic command:

- /shadoweval [id]  — show most recent eval for a specific proposal,
                      or a summary of all shadow evals if id omitted.

Spec: docs/plans/OIL_BOT_PATTERN_06_SELF_TUNE_HARNESS.md §L4
"""
from __future__ import annotations


OIL_BOTPATTERN_SHADOW_EVALS_JSONL = "data/strategy/oil_botpattern_shadow_evals.jsonl"
OIL_BOTPATTERN_PROPOSALS_JSONL = "data/strategy/oil_botpattern_proposals.jsonl"


def cmd_shadoweval(token: str, chat_id: str, args: str) -> None:
    """Show L4 counterfactual shadow-eval results.

    Usage: /shadoweval          — summary of all evaluated proposals
           /shadoweval <id>     — detailed eval for a specific proposal
    """
    from cli.daemon.iterators.oil_botpattern_reflect import load_proposals
    from cli.daemon.iterators.oil_botpattern_shadow import (
        find_shadow_eval,
        load_shadow_evals,
    )
    from cli.telegram_bot import tg_send

    arg = (args or "").strip()
    evals = load_shadow_evals(OIL_BOTPATTERN_SHADOW_EVALS_JSONL)

    if not arg:
        # Summary mode
        if not evals:
            tg_send(
                token, chat_id,
                "🌓 No shadow evaluations yet. L4 runs counterfactual "
                "replays of approved L2 proposals — check /selftune for "
                "harness state.",
                markdown=True,
            )
            return

        lines = [f"🌓 *Shadow evaluations* (last {min(10, len(evals))} of {len(evals)})", ""]
        for e in evals[-10:][::-1]:
            pid = e.get("proposal_id", "?")
            param = e.get("param", "?")
            old = e.get("current_value", "?")
            new = e.get("proposed_value", "?")
            div = e.get("would_have_diverged", 0)
            rate = e.get("divergence_rate", 0.0)
            pnl = e.get("counterfactual_pnl_estimate_usd", 0.0)
            sample_ok = "✅" if e.get("sample_sufficient") else "⚠️"
            ts = (e.get("evaluated_at") or "")[:10]
            lines.append(
                f"*#{pid}* `{param}` {old} → {new}  "
                f"diverge={div} ({rate:.0%}) est=${pnl:+,.0f} {sample_ok} ({ts})"
            )
        lines.append("")
        lines.append("_Use_ `/shadoweval <id>` _for a detailed eval._")
        tg_send(token, chat_id, "\n".join(lines), markdown=True)
        return

    # Detail mode
    try:
        proposal_id = int(arg)
    except ValueError:
        tg_send(token, chat_id, f"Bad id: `{arg}`. Integer expected.", markdown=True)
        return

    eval_row = find_shadow_eval(evals, proposal_id)
    if eval_row is None:
        tg_send(
            token, chat_id,
            f"🌓 No shadow evaluation found for proposal #{proposal_id}. "
            f"Evaluations run on approved L2 proposals once L4 is enabled.",
            markdown=True,
        )
        return

    # Pull the proposal itself for description
    proposals = load_proposals(OIL_BOTPATTERN_PROPOSALS_JSONL)
    proposal = None
    for p in proposals:
        try:
            if int(p.get("id", -1)) == proposal_id:
                proposal = p
                break
        except (TypeError, ValueError):
            continue

    lines = [f"🌓 *Shadow eval #{proposal_id}*", ""]
    if proposal:
        lines.append(f"*Type:* `{proposal.get('type', '?')}`")
        lines.append(f"*Description:* {proposal.get('description', '(none)')}")
        lines.append("")

    lines.append(f"*Param:* `{eval_row.get('param', '?')}`")
    lines.append(
        f"*Swap:* {eval_row.get('current_value')} → {eval_row.get('proposed_value')}"
    )
    lines.append("")
    lines.append("*Counterfactual replay:*")
    lines.append(f"  window: {eval_row.get('window_days', '?')} days")
    lines.append(f"  trades in window: {eval_row.get('trades_in_window', 0)}")
    lines.append(f"  decisions in window: {eval_row.get('decisions_in_window', 0)}")
    lines.append(f"  unchanged outcomes: {eval_row.get('would_have_entered_same', 0)}")
    lines.append(f"  diverged outcomes: {eval_row.get('would_have_diverged', 0)}")
    lines.append(f"  divergence rate: {eval_row.get('divergence_rate', 0.0):.0%}")
    pnl = eval_row.get("counterfactual_pnl_estimate_usd", 0.0)
    lines.append(f"  est. PnL delta: ${pnl:+,.2f}")
    lines.append("")

    if eval_row.get("sample_sufficient"):
        lines.append("✅ Sample sufficient.")
    else:
        lines.append("⚠️ Sample insufficient — interpret with caution.")

    notes = eval_row.get("notes")
    if notes:
        lines.append("")
        lines.append(f"_{notes}_")

    tg_send(token, chat_id, "\n".join(lines), markdown=True)
