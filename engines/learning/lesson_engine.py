"""Trade lesson engine — pure computation, zero I/O.

Builds verbatim post-mortem requests from closed JournalEntry data and parses
the agent's response back into structured Lesson records. Persistence lives in
common/memory.py (the canonical owner of data/memory/memory.db).

Engine vs guard split: this module follows the modules/CLAUDE.md rule that
engines are pure computation. The persistence layer is common/memory.py
(log_lesson, get_lesson, search_lessons, set_lesson_review). Daemon iterators
call the engine to build the request and parse the response, then call
common.memory functions to persist.
"""
from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


# ---------------------------------------------------------------------------
# Constants — keep in lockstep with the lessons table CHECK constraints in
# common/memory.py:_init().
# ---------------------------------------------------------------------------

VALID_DIRECTIONS = ("long", "short", "flat")
VALID_OUTCOMES = ("win", "loss", "breakeven", "scratched")

LESSON_TYPES = (
    "sizing",
    "entry_timing",
    "exit_quality",
    "thesis_invalidation",
    "funding_carry",
    "catalyst_timing",
    "pattern_recognition",
)


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class Lesson:
    """A structured trade post-mortem.

    The body_full column is verbatim — it MUST contain the assembled context
    (thesis snapshot + entry reasoning + journal retrospective + autoresearch
    eval window + news context) plus the agent's analysis. No information from
    the source is ever discarded. The summary is a 1-3 sentence pointer for
    prompt-injection ranking, NOT a replacement for the body.
    """
    id: int = 0  # populated after insert
    created_at: str = ""           # ISO 8601
    trade_closed_at: str = ""      # ISO 8601
    market: str = ""
    direction: str = ""            # one of VALID_DIRECTIONS
    signal_source: str = ""        # 'radar', 'pulse_signal', 'pulse_immediate', 'manual', 'thesis_driven', ...
    lesson_type: str = ""          # one of LESSON_TYPES
    outcome: str = ""              # one of VALID_OUTCOMES
    pnl_usd: float = 0.0
    roe_pct: float = 0.0
    holding_ms: int = 0
    conviction_at_open: Optional[float] = None
    journal_entry_id: Optional[str] = None
    thesis_snapshot_path: Optional[str] = None
    summary: str = ""              # 1-3 sentences, agent-authored, prompt-injected
    body_full: str = ""            # verbatim assembled context + agent analysis. NEVER summarized.
    tags: List[str] = field(default_factory=list)
    reviewed_by_chris: int = 0     # 0 = unreviewed, 1 = approved, -1 = rejected

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "created_at": self.created_at,
            "trade_closed_at": self.trade_closed_at,
            "market": self.market,
            "direction": self.direction,
            "signal_source": self.signal_source,
            "lesson_type": self.lesson_type,
            "outcome": self.outcome,
            "pnl_usd": round(self.pnl_usd, 4),
            "roe_pct": round(self.roe_pct, 2),
            "holding_ms": self.holding_ms,
            "conviction_at_open": self.conviction_at_open,
            "journal_entry_id": self.journal_entry_id,
            "thesis_snapshot_path": self.thesis_snapshot_path,
            "summary": self.summary,
            "body_full": self.body_full,
            "tags": list(self.tags),
            "reviewed_by_chris": self.reviewed_by_chris,
        }

    @classmethod
    def from_dict(cls, d: dict) -> Lesson:
        # Tolerate JSON-string tags from SQLite roundtrip.
        tags = d.get("tags", [])
        if isinstance(tags, str):
            try:
                tags = json.loads(tags) if tags else []
            except (ValueError, TypeError):
                tags = []
        return cls(
            id=d.get("id", 0),
            created_at=d.get("created_at", ""),
            trade_closed_at=d.get("trade_closed_at", ""),
            market=d.get("market", ""),
            direction=d.get("direction", ""),
            signal_source=d.get("signal_source", ""),
            lesson_type=d.get("lesson_type", ""),
            outcome=d.get("outcome", ""),
            pnl_usd=d.get("pnl_usd", 0.0),
            roe_pct=d.get("roe_pct", 0.0),
            holding_ms=d.get("holding_ms", 0),
            conviction_at_open=d.get("conviction_at_open"),
            journal_entry_id=d.get("journal_entry_id"),
            thesis_snapshot_path=d.get("thesis_snapshot_path"),
            summary=d.get("summary", ""),
            body_full=d.get("body_full", ""),
            tags=list(tags) if isinstance(tags, (list, tuple)) else [],
            reviewed_by_chris=d.get("reviewed_by_chris", 0),
        )


@dataclass
class LessonAuthorRequest:
    """Verbatim context bundle handed to the agent to author a lesson.

    Every field below is read directly from existing on-disk artefacts
    (JournalEntry, ThesisState snapshot, learnings.md slice, news context).
    Nothing is summarized or pruned at this stage — the agent will write the
    summary, but the body_full it persists must include all of this verbatim.
    """
    journal_entry: Dict[str, Any] = field(default_factory=dict)
    thesis_snapshot: Optional[Dict[str, Any]] = None
    thesis_snapshot_path: Optional[str] = None
    learnings_md_slice: str = ""
    news_context_at_open: str = ""
    autoresearch_eval_window: str = ""

    def assemble_context_block(self) -> str:
        """Concatenate all verbatim source material in a stable order.

        The agent will be told to copy this block intact into the body_full
        column of the lesson it authors. Stable ordering matters because the
        BM25 ranker uses the body content for retrieval — sections jumping
        around between lessons makes ranking less consistent.
        """
        parts: List[str] = []

        je = self.journal_entry or {}
        if je:
            parts.append("### journal_entry")
            parts.append("```json")
            parts.append(json.dumps(je, indent=2, sort_keys=True, default=str))
            parts.append("```")

        if self.thesis_snapshot:
            parts.append("### thesis_snapshot_at_open")
            if self.thesis_snapshot_path:
                parts.append(f"_source: {self.thesis_snapshot_path}_")
            parts.append("```json")
            parts.append(json.dumps(self.thesis_snapshot, indent=2, sort_keys=True, default=str))
            parts.append("```")

        if self.learnings_md_slice.strip():
            parts.append("### learnings_md_slice")
            parts.append(self.learnings_md_slice.rstrip())

        if self.autoresearch_eval_window.strip():
            parts.append("### autoresearch_eval_window")
            parts.append(self.autoresearch_eval_window.rstrip())

        if self.news_context_at_open.strip():
            parts.append("### news_context_at_open")
            parts.append(self.news_context_at_open.rstrip())

        return "\n\n".join(parts)


# ---------------------------------------------------------------------------
# Pure engine
# ---------------------------------------------------------------------------

# A unique sentinel the agent must wrap its summary in. Easier and stricter
# than free-form parsing because the agent knows this sentinel will be matched
# verbatim — there is no JSON to escape.
_SUMMARY_OPEN = "<<<LESSON_SUMMARY>>>"
_SUMMARY_CLOSE = "<<<END_LESSON_SUMMARY>>>"
_TAGS_OPEN = "<<<LESSON_TAGS>>>"
_TAGS_CLOSE = "<<<END_LESSON_TAGS>>>"
_LESSON_TYPE_OPEN = "<<<LESSON_TYPE>>>"
_LESSON_TYPE_CLOSE = "<<<END_LESSON_TYPE>>>"


class LessonEngine:
    """Pure lesson logic. Zero I/O."""

    @staticmethod
    def now_iso() -> str:
        return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    @staticmethod
    def classify_outcome(pnl_usd: float, roe_pct: float) -> str:
        """Map PnL to one of VALID_OUTCOMES.

        Conservative bands: |roe| < 0.5% counts as breakeven, anything else is
        win/loss. 'scratched' is reserved for the iterator to set when an
        entry was opened and immediately closed without a thesis-driven exit
        (e.g. user manual close inside the first minute) — the engine cannot
        infer that from PnL alone.
        """
        if abs(roe_pct) < 0.5:
            return "breakeven"
        return "win" if pnl_usd > 0 else "loss"

    def build_lesson_prompt(self, request: LessonAuthorRequest) -> str:
        """Build the prompt the agent receives to author a lesson.

        The prompt is fixed-shape and asks the agent for three sentinel-wrapped
        outputs (summary, lesson_type, tags) followed by the verbatim body.
        Sentinels are easier to parse than free-form JSON and impossible for
        the agent to forget if the prompt is explicit.
        """
        je = request.journal_entry or {}
        instrument = je.get("instrument", "(unknown)")
        direction = je.get("direction", "(unknown)")
        roe = je.get("roe_pct", 0.0)
        close_reason = je.get("close_reason", "(unknown)")

        context_block = request.assemble_context_block()

        return f"""You just closed a trade. Write a verbatim post-mortem so a future you can recall what happened the next time a similar setup appears.

Trade: {instrument} {direction}, ROE {roe:+.2f}%, close reason: {close_reason}

You will be given the full verbatim context below. Your job:

1. Read everything carefully.
2. Decide which lesson_type best fits this trade. Pick exactly one of:
   {", ".join(LESSON_TYPES)}
3. Write a structured analysis with these five sections:
   (a) what happened
   (b) what worked
   (c) what didn't
   (d) what pattern this is part of
   (e) what you'd do differently next time
4. Write a 1-3 sentence summary that a future you would search for. Include
   the market, direction, the key cause-and-effect, and the outcome. Avoid
   filler. This is the line that gets injected into the prompt next time.
5. Write up to 8 short tags (lowercase, hyphenated). Examples:
   "weekend-wick", "fed-day", "stop-hunt", "thesis-confirmed",
   "supply-disruption", "entry-too-late", "stop-too-tight".

Format your response EXACTLY like this, with the sentinels copied verbatim:

{_LESSON_TYPE_OPEN}
<one of: {", ".join(LESSON_TYPES)}>
{_LESSON_TYPE_CLOSE}

{_SUMMARY_OPEN}
<your 1-3 sentence summary here>
{_SUMMARY_CLOSE}

{_TAGS_OPEN}
<comma-separated tags here>
{_TAGS_CLOSE}

## Analysis

(a) what happened: ...
(b) what worked: ...
(c) what didn't: ...
(d) what pattern this is part of: ...
(e) what you'd do differently next time: ...

## Verbatim source context

(Copy the entire context block below INTO your response, unchanged. Do not
summarize it. Do not omit any section. The body_full column will be the full
text of your response from the analysis section onward, including this
verbatim context.)

{context_block}
"""

    def parse_lesson_response(
        self,
        response_text: str,
        request: LessonAuthorRequest,
        market: str,
        direction: str,
        signal_source: str,
        pnl_usd: float,
        roe_pct: float,
        holding_ms: int,
        trade_closed_at: str,
        conviction_at_open: Optional[float] = None,
        journal_entry_id: Optional[str] = None,
        thesis_snapshot_path: Optional[str] = None,
        now_iso: Optional[str] = None,
    ) -> Lesson:
        """Parse the agent's response into a Lesson record.

        Sentinel extraction is strict: if a required sentinel block is
        missing, raises ValueError. The iterator should catch and log without
        inserting — better to lose one lesson than corrupt the corpus
        (Bug A pattern from 2026-04-08 build log entry).
        """
        if direction not in VALID_DIRECTIONS:
            raise ValueError(f"direction must be one of {VALID_DIRECTIONS}, got {direction!r}")

        lesson_type = self._extract_sentinel(
            response_text, _LESSON_TYPE_OPEN, _LESSON_TYPE_CLOSE, "lesson_type",
        ).strip().lower()
        if lesson_type not in LESSON_TYPES:
            raise ValueError(
                f"lesson_type must be one of {LESSON_TYPES}, got {lesson_type!r}"
            )

        summary = self._extract_sentinel(
            response_text, _SUMMARY_OPEN, _SUMMARY_CLOSE, "summary",
        ).strip()
        if not summary:
            raise ValueError("summary sentinel block was empty")

        tags_raw = self._extract_sentinel(
            response_text, _TAGS_OPEN, _TAGS_CLOSE, "tags",
        )
        tags = [t.strip().lower() for t in tags_raw.split(",") if t.strip()]
        # Cap and dedupe while preserving order.
        seen: set = set()
        deduped: List[str] = []
        for t in tags:
            if t not in seen:
                seen.add(t)
                deduped.append(t)
            if len(deduped) >= 8:
                break
        tags = deduped

        # body_full is the full agent response, sentinels stripped, with the
        # verbatim source context appended unconditionally as a safety net.
        # If the agent forgot to copy the context (model drift), the safety
        # net guarantees the verbatim source is still preserved.
        body_full = self._strip_sentinels(response_text).strip()
        context_block = request.assemble_context_block()
        if context_block and context_block not in body_full:
            body_full = f"{body_full}\n\n## Verbatim source context (auto-attached)\n\n{context_block}"

        outcome = self.classify_outcome(pnl_usd, roe_pct)

        return Lesson(
            id=0,
            created_at=now_iso or self.now_iso(),
            trade_closed_at=trade_closed_at,
            market=market,
            direction=direction,
            signal_source=signal_source,
            lesson_type=lesson_type,
            outcome=outcome,
            pnl_usd=pnl_usd,
            roe_pct=roe_pct,
            holding_ms=holding_ms,
            conviction_at_open=conviction_at_open,
            journal_entry_id=journal_entry_id,
            thesis_snapshot_path=thesis_snapshot_path,
            summary=summary,
            body_full=body_full,
            tags=tags,
            reviewed_by_chris=0,
        )

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_sentinel(text: str, open_tag: str, close_tag: str, label: str) -> str:
        pattern = re.escape(open_tag) + r"(.*?)" + re.escape(close_tag)
        m = re.search(pattern, text, re.DOTALL)
        if not m:
            raise ValueError(
                f"missing {label} sentinel block ({open_tag}...{close_tag})"
            )
        return m.group(1)

    @staticmethod
    def _strip_sentinels(text: str) -> str:
        for tag in (
            _LESSON_TYPE_OPEN, _LESSON_TYPE_CLOSE,
            _SUMMARY_OPEN, _SUMMARY_CLOSE,
            _TAGS_OPEN, _TAGS_CLOSE,
        ):
            text = text.replace(tag, "")
        return text
