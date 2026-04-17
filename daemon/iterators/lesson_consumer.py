"""LessonConsumerIterator — autonomous closed-loop lesson authoring.

Scans ``data/daemon/lesson_candidates/`` for pending candidate files written
by ``LessonAuthorIterator`` (wedge 5) and calls the agent to author a
structured post-mortem for each one, persisting the result to the FTS5 lessons
table in ``common/memory.py``.

This is wedge 6 of the trade lesson layer — it closes the loop that
``lesson_author.py`` (wedge 5) opens:

    closed trade
        → journal.jsonl
            → lesson_author (wedge 5): candidate file
                → lesson_consumer (wedge 6): lessons table in memory.db
                    → BM25 recall injected into agent prompt on next trade

Design decisions
----------------
* Tick cadence: only processes at most ``batch_size`` (default 3) candidates per
  tick — per NORTH_STAR P10 (bound the read path).
* Minimum inter-run interval: ``min_interval_s`` (default 3600s = 1h).  The
  iterator skips its work if the last successful run was more recent than the
  interval.  This prevents the daemon from hammering the model on every 60s tick.
* Atomic file ops: candidates are only deleted after a lesson row is
  successfully inserted.  Failure at any stage leaves the candidate in place for
  the next run.
* Idempotency: checks ``journal_entry_id`` against the existing lesson corpus
  before inserting.  If a lesson with the same id already exists (e.g. the
  command ``/lessonauthorai`` ran manually in the interim), the candidate is
  deleted without a model call.
* Model: delegates entirely to ``telegram.agent._author_pending_lessons``, which
  uses ``_call_anthropic`` with ``model_override="claude-haiku-4-5"`` — the same
  path the dream cycle and ``/lessonauthorai`` use.  No model hardcoding here.

Kill switch: ``data/config/lesson_consumer.json`` → ``{"enabled": false}``
Default: **disabled** (``enabled: false``).  Chris flips it on when he's ready.

Registration
-----------
* ``daemon/tiers.py`` — listed in every tier after ``lesson_author``
* ``cli/commands/daemon.py`` — registered via try/except import (same pattern
  as other optional iterators)
"""
from __future__ import annotations

import json
import logging
import time
from pathlib import Path

from daemon.context import TickContext

log = logging.getLogger("daemon.lesson_consumer")

DEFAULT_CONFIG_PATH = "data/config/lesson_consumer.json"
DEFAULT_CANDIDATE_DIR = "data/daemon/lesson_candidates"
DEFAULT_STATE_PATH = "data/daemon/lesson_consumer_state.json"

# Safety constants
_DEFAULT_BATCH_SIZE = 3
_DEFAULT_MIN_INTERVAL_S = 3600  # 1 hour between processing runs


class LessonConsumerIterator:
    """Daemon iterator that converts lesson candidates into authored lessons.

    This iterator is intentionally thin — all the heavy logic (LessonEngine
    prompt build, ``_call_anthropic``, ``parse_lesson_response``,
    ``log_lesson``) lives in ``telegram.agent._author_pending_lessons``.
    The iterator is just a scheduler + kill-switch wrapper.
    """

    name = "lesson_consumer"

    def __init__(
        self,
        config_path: str = DEFAULT_CONFIG_PATH,
        candidate_dir: str = DEFAULT_CANDIDATE_DIR,
        state_path: str = DEFAULT_STATE_PATH,
    ):
        self._config_path = Path(config_path)
        self._candidate_dir = Path(candidate_dir)
        self._state_path = Path(state_path)
        self._enabled: bool = False  # default OFF — Chris flips via config
        self._batch_size: int = _DEFAULT_BATCH_SIZE
        self._min_interval_s: int = _DEFAULT_MIN_INTERVAL_S
        self._last_run_ts: float = 0.0

    # ── Lifecycle ────────────────────────────────────────────

    def on_start(self, ctx: TickContext) -> None:
        self._reload_config()
        self._load_state()
        if self._enabled:
            log.info(
                "LessonConsumerIterator started (batch=%d, interval=%ds, last_run=%s)",
                self._batch_size,
                self._min_interval_s,
                time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(self._last_run_ts))
                if self._last_run_ts
                else "never",
            )
        else:
            log.info("LessonConsumerIterator disabled via config — no-op")

    def on_stop(self) -> None:
        self._save_state()

    def tick(self, ctx: TickContext) -> None:
        self._reload_config()
        if not self._enabled:
            return

        # Rate-limit: skip if we ran recently.
        now = time.time()
        elapsed = now - self._last_run_ts
        if elapsed < self._min_interval_s:
            log.debug(
                "LessonConsumer: skipping tick (elapsed=%ds < min=%ds)",
                int(elapsed),
                self._min_interval_s,
            )
            return

        # Fast path: nothing to do if the candidate dir is empty.
        if not self._candidate_dir.exists():
            return
        candidates = list(self._candidate_dir.glob("*.json"))
        if not candidates:
            return

        pending = len(candidates)
        log.info(
            "LessonConsumer: processing up to %d/%d pending candidates",
            self._batch_size,
            pending,
        )

        try:
            from telegram.agent import _author_pending_lessons
            result = _author_pending_lessons(
                max_lessons=self._batch_size,
                candidate_dir=str(self._candidate_dir),
            )
        except Exception as e:
            log.warning(
                "LessonConsumer: _author_pending_lessons raised: %s — will retry next tick",
                e,
            )
            return

        processed = result.get("processed", 0)
        failed = result.get("failed", 0)
        errors = result.get("errors") or []

        if processed or failed:
            log.info(
                "LessonConsumer: processed=%d, failed=%d (pending was %d)",
                processed,
                failed,
                pending,
            )
        if errors:
            for err in errors[:5]:
                log.warning("LessonConsumer: candidate error: %s", err)

        # Update state on every run (success or partial failure).
        self._last_run_ts = now
        self._save_state()

    # ── Config + state ───────────────────────────────────────

    def _reload_config(self) -> None:
        """Re-read the kill switch file on every tick so a config flip takes
        effect at the next tick without a daemon restart."""
        if not self._config_path.exists():
            # Default: OFF. The operator must explicitly enable.
            self._enabled = False
            return
        try:
            with self._config_path.open("r") as f:
                cfg = json.load(f)
            self._enabled = bool(cfg.get("enabled", False))
            self._batch_size = max(1, int(cfg.get("batch_size", _DEFAULT_BATCH_SIZE)))
            self._min_interval_s = max(60, int(cfg.get("min_interval_s", _DEFAULT_MIN_INTERVAL_S)))
        except (OSError, json.JSONDecodeError, ValueError) as e:
            log.warning(
                "LessonConsumer: bad config %s: %s — defaulting to disabled",
                self._config_path,
                e,
            )
            self._enabled = False

    def _load_state(self) -> None:
        if not self._state_path.exists():
            self._last_run_ts = 0.0
            return
        try:
            with self._state_path.open("r") as f:
                state = json.load(f)
            self._last_run_ts = float(state.get("last_run_ts", 0.0))
        except (OSError, json.JSONDecodeError, ValueError) as e:
            log.warning(
                "LessonConsumer: bad state %s: %s — resetting",
                self._state_path,
                e,
            )
            self._last_run_ts = 0.0

    def _save_state(self) -> None:
        try:
            self._state_path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self._state_path.with_suffix(".tmp")
            with tmp.open("w") as f:
                json.dump({"last_run_ts": self._last_run_ts}, f)
            tmp.replace(self._state_path)
        except OSError as e:
            log.warning("LessonConsumer: failed to save state: %s", e)
