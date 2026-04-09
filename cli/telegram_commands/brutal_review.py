"""Brutal Review Loop Telegram command — wedge 1.

The user explicitly asked (2026-04-09) for a system that gives the kind
of brutally honest deep-dive feedback the manual review session produced.
This is the on-demand version. Future wedges add scheduled cadence,
action queue, and decision-quality grading.

The /brutalreviewai command:
1. Loads the literal system prompt from docs/plans/BRUTAL_REVIEW_PROMPT.md
2. Hands it to the agent via the existing telegram_agent.handle_ai_message
   path
3. The agent's response is written to data/reviews/brutal_review_YYYY-MM-DD.md
4. A short Telegram acknowledgment is sent immediately

Per CLAUDE.md slash-command rule, this is AI-suffixed because the entire
output is model-authored.
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

BRUTAL_REVIEW_PROMPT_PATH = "docs/plans/BRUTAL_REVIEW_PROMPT.md"
BRUTAL_REVIEW_OUTPUT_DIR = "data/reviews"


def cmd_brutalreviewai(token: str, chat_id: str, args: str) -> None:
    """Run the Brutal Review Loop on demand.

    AI-dependent — hands the literal BRUTAL_REVIEW_PROMPT.md to the
    agent for a deep audit pass. The agent's full output lands on disk
    at ``data/reviews/brutal_review_YYYY-MM-DD.md`` and a short summary
    posts back to Telegram.

    Usage:
        /brutalreviewai            — run the full review pass

    Cost: one full agent invocation (Sonnet by default, ~30-60s wall
    time, free under session-token auth). Run weekly or on demand
    after a major architectural change.
    """
    from cli.telegram_bot import tg_send

    prompt_path = Path(BRUTAL_REVIEW_PROMPT_PATH)
    if not prompt_path.exists():
        tg_send(
            token,
            chat_id,
            f"❌ Brutal review prompt not found at `{BRUTAL_REVIEW_PROMPT_PATH}`. "
            "Did the file get moved?",
        )
        return

    try:
        prompt = prompt_path.read_text()
    except OSError as e:
        tg_send(token, chat_id, f"❌ Failed to read prompt: {e}")
        return

    out_dir = Path(BRUTAL_REVIEW_OUTPUT_DIR)
    out_dir.mkdir(parents=True, exist_ok=True)
    date_slug = datetime.now().strftime("%Y-%m-%d")
    output_path = out_dir / f"brutal_review_{date_slug}.md"

    # Acknowledge immediately so the user knows the review started
    tg_send(
        token,
        chat_id,
        f"🔍 *Brutal Review Loop starting…*\n\n"
        f"Loaded prompt from `{BRUTAL_REVIEW_PROMPT_PATH}` "
        f"({len(prompt):,} chars).\n\n"
        f"Output will land at `{output_path}`.\n\n"
        f"This may take 30-60s. The full report goes to disk; a summary "
        f"posts back here when done.",
    )

    # Hand the prompt to the agent. handle_ai_message routes through
    # telegram_agent and the agent runtime, which knows how to use tools.
    try:
        from cli.telegram_agent import handle_ai_message
    except ImportError:
        tg_send(
            token,
            chat_id,
            "❌ Brutal review unavailable — `cli.telegram_agent` not loaded.",
        )
        return

    # The agent will read its grounding files, run the audit, and write
    # the report. We pass an instruction that tells the agent where to
    # write the output so it lands on disk regardless of streaming
    # behavior.
    augmented = (
        f"{prompt}\n\n---\n\n"
        f"## EXECUTION INSTRUCTIONS FOR THIS RUN\n\n"
        f"Today's date: {date_slug}.\n\n"
        f"Write your full report to `{output_path}` using the `edit_file` "
        f"or `run_bash` tool. After writing, post a SHORT Telegram summary "
        f"with: top 3 brutal observations + top 3 action items + a link "
        f"to the report file. Total Telegram message must fit in one "
        f"message (<3000 chars).\n"
    )

    try:
        handle_ai_message(token, chat_id, augmented)
    except Exception as e:
        tg_send(token, chat_id, f"❌ Brutal review failed: {e}")
        return
