"""Sub-system 6 L3 pattern library Telegram commands.

Part of the incremental telegram_bot.py monolith split. L3 grows the
bot-pattern catalog observationally — the iterator tallies novel
signatures in data/research/bot_patterns.jsonl and writes candidates
to data/research/bot_pattern_candidates.jsonl once `min_occurrences`
is met. These commands front that pipeline.

Three deterministic commands (no `ai` suffix — all output is code-
generated from templates):

- /patterncatalog        — show live catalog + pending candidates
- /patternpromote <id>   — promote a pending candidate into the live catalog
- /patternreject <id>    — reject a pending candidate (catalog untouched)

Spec: docs/plans/OIL_BOT_PATTERN_06_SELF_TUNE_HARNESS.md §L3

The 5-surface checklist (HANDLERS dict, _set_telegram_commands,
cmd_help, cmd_guide) is satisfied from cli/telegram_bot.py — this file
just hosts the handler bodies per the `cli/telegram_commands/`
convention.
"""
from __future__ import annotations

from datetime import datetime, timezone


# Paths are centralized here so both the command handlers and any unit
# tests can patch them via `cli.telegram_commands.patternlib.*`.
OIL_BOTPATTERN_PATTERN_CATALOG_JSON = "data/research/bot_pattern_catalog.json"
OIL_BOTPATTERN_PATTERN_CANDIDATES_JSONL = "data/research/bot_pattern_candidates.jsonl"


def cmd_patterncatalog(token: str, chat_id: str, _args: str) -> None:
    """Show the live bot-pattern catalog + pending candidates."""
    from daemon.iterators.oil_botpattern_patternlib import (
        load_candidates,
        load_catalog,
    )
    from cli.telegram_bot import tg_send  # lazy — avoids circular import

    catalog = load_catalog(OIL_BOTPATTERN_PATTERN_CATALOG_JSON)
    candidates = load_candidates(OIL_BOTPATTERN_PATTERN_CANDIDATES_JSONL)
    pending = [c for c in candidates if c.get("status") == "pending"]

    lines = ["📚 *Bot-pattern library (sub-system 6 L3)*", ""]
    lines.append(f"*Live catalog entries:* {len(catalog)}")
    lines.append(f"*Pending candidates:* {len(pending)}")
    lines.append(f"*Total candidates (all statuses):* {len(candidates)}")
    lines.append("")

    if catalog:
        lines.append("*Live signatures (top 5 by promotion date):*")
        items = sorted(
            catalog.items(),
            key=lambda kv: kv[1].get("promoted_at", ""),
            reverse=True,
        )
        for _key, entry in items[:5]:
            cls = entry.get("classification", "?")
            direction = entry.get("direction", "?")
            conf = entry.get("confidence_band", 0.0)
            promoted = (entry.get("promoted_at") or "")[:10]
            signals = entry.get("signals") or []
            sig_str = "|".join(signals) if signals else "∅"
            lines.append(
                f"  `{cls}` {direction} conf={conf:.2f} [{sig_str}]  ({promoted})"
            )
        lines.append("")

    if pending:
        lines.append(f"*Pending candidates (newest {min(5, len(pending))}):*")
        for c in pending[-5:][::-1]:
            cid = c.get("id", "?")
            cls = c.get("classification", "?")
            direction = c.get("direction", "?")
            conf = c.get("confidence_band", 0.0)
            occ = c.get("occurrences", 0)
            signals = c.get("signals") or []
            sig_str = "|".join(signals) if signals else "∅"
            lines.append(
                f"  *#{cid}* `{cls}` {direction} conf={conf:.2f} "
                f"[{sig_str}] ×{occ}"
            )
            lines.append(f"      `/patternpromote {cid}`  `/patternreject {cid}`")
        lines.append("")

    lines.append(
        "_L3 grows the catalog observationally. Promotion updates the "
        "live set but does NOT yet change classifier behavior — that's "
        "a future wedge._"
    )

    tg_send(token, chat_id, "\n".join(lines), markdown=True)


def cmd_patternpromote(token: str, chat_id: str, args: str) -> None:
    """Promote a pending bot-pattern candidate into the live catalog.

    Usage: /patternpromote <id>
    """
    from daemon.iterators.oil_botpattern_patternlib import apply_promote
    from cli.telegram_bot import tg_send

    arg = (args or "").strip()
    if not arg:
        tg_send(token, chat_id, "Usage: `/patternpromote <id>`", markdown=True)
        return
    try:
        cid = int(arg)
    except ValueError:
        tg_send(token, chat_id, f"Bad id: `{arg}`. Integer expected.", markdown=True)
        return

    now_iso = datetime.now(tz=timezone.utc).isoformat()
    ok, msg = apply_promote(
        OIL_BOTPATTERN_PATTERN_CATALOG_JSON,
        OIL_BOTPATTERN_PATTERN_CANDIDATES_JSONL,
        cid,
        now_iso,
    )
    if ok:
        tg_send(token, chat_id, f"✅ {msg}", markdown=True)
    else:
        tg_send(token, chat_id, f"⚠️ {msg}", markdown=True)


def cmd_patternreject(token: str, chat_id: str, args: str) -> None:
    """Reject a pending bot-pattern candidate. Catalog not touched.

    Usage: /patternreject <id>
    """
    from daemon.iterators.oil_botpattern_patternlib import apply_reject
    from cli.telegram_bot import tg_send

    arg = (args or "").strip()
    if not arg:
        tg_send(token, chat_id, "Usage: `/patternreject <id>`", markdown=True)
        return
    try:
        cid = int(arg)
    except ValueError:
        tg_send(token, chat_id, f"Bad id: `{arg}`. Integer expected.", markdown=True)
        return

    now_iso = datetime.now(tz=timezone.utc).isoformat()
    ok, msg = apply_reject(
        OIL_BOTPATTERN_PATTERN_CANDIDATES_JSONL,
        cid,
        now_iso,
    )
    if ok:
        tg_send(token, chat_id, f"❌ {msg}", markdown=True)
    else:
        tg_send(token, chat_id, f"⚠️ {msg}", markdown=True)
