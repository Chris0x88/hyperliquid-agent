# WHY_PARKED: architect_engine.py

**Archived:** 2026-04-17
**Archived by:** Claude Code (architectural cleanup session)
**Reason:** Functionally superseded by Sub-6 L2 (`oil_botpattern_reflect`)

---

## What was archived

| File | Original path |
|------|--------------|
| `architect_engine.py` | `engines/learning/architect_engine.py` |
| `architect.py` (iterator) | `daemon/iterators/architect.py` |
| `architect.py` (CLI) | `cli/commands/architect.py` |
| `architect.json` (config) | `data/config/architect.json` |

---

## Why it was superseded

The Architect Engine implements a three-step loop:
1. **Detect** — read autoresearch evaluation files + issues.jsonl, find recurring patterns (noise_exits_dominant, sizing_drift, funding_drag, catalyst_timing_poor)
2. **Hypothesize** — translate each pattern into a concrete config-change proposal
3. **Propose** — surface pending proposals for human 1-tap approval/rejection

Sub-6 Layer 2 (`oil_botpattern_reflect`, `trading/oil/reflect.py`) does **exactly the same thing**, but:

- Is **oil-specific and concrete** rather than generic/abstract (patterns read real closed trade data from `data/strategy/oil_botpattern_journal.jsonl` and decision records, not abstract "evaluation" files)
- Has a **complete, tested implementation** — 191 tests passing as of archive date
- Targets **`oil_botpattern.json`** via `StructuralProposal` records — exactly the same config files architect's proposals pointed at
- Has a **production Telegram surface** (`/selftuneproposals`, `/selftuneapprove`, `/selftunereject`) with approval/rejection audit trail
- Is registered in **REBALANCE + OPPORTUNISTIC** (the correct tiers for strategy improvement)
- Ships with `enabled=false` kill switch, same as Architect

The critical difference: Architect's pattern detectors read `data/research/evaluations/*.json` — a directory that nothing in the live codebase populates today. Its `sizing_alignment_score`, `stops_noise_exit`, `funding_efficiency_score`, and `catalyst_timing_score` fields are fields that no live writer produces. The engine was structurally sound but starved of input.

Sub-6 L2 reads from `data/strategy/oil_botpattern_journal.jsonl` which IS actively written by sub-system 5 on every decision tick.

---

## What was cleaned up

- Removed `"architect"` from all three tiers in `daemon/tiers.py`
- Removed the `try/import ArchitectIterator` block in `cli/commands/daemon.py`
- Removed `from cli.commands.architect import app as architect_app` + `app.add_typer(architect_app, ...)` from `cli/main.py`
- Removed `cmd_architect`, HANDLERS entries (`/architect`, `architect`), `_set_telegram_commands` entry, and help text from `telegram/bot.py`
- Updated `daemon/CLAUDE.md` to mark architect as archived
- Updated `engines/CLAUDE.md` to mark architect_engine as archived
- Updated `docs/wiki/learning-paths/understanding-config.md` to note architect.json as archived

---

## How to resurrect

If a generic multi-strategy self-improvement layer is needed again:

1. Move files back to their original locations (reverse the git mv)
2. Populate `data/research/evaluations/` — you need a writer (likely an updated autoresearch iterator) that produces JSON with fields: `stops_noise_exit`, `stops_thesis_invalidation`, `sizing_alignment_score`, `funding_paid_usd`, `funding_efficiency_score`, `catalyst_timing_score`, `timestamp_human`
3. Re-add `"architect"` to `daemon/tiers.py` (watch/rebalance/opportunistic)
4. Re-add the import block in `cli/commands/daemon.py`
5. Re-add `architect_app` registration in `cli/main.py`
6. Re-add `cmd_architect` and handlers in `telegram/bot.py`
7. Set `data/config/architect.json → enabled: true`
8. Run full test suite

Alternatively, consider extending Sub-6 L2 to handle multi-strategy patterns rather than resurrecting the generic Architect Engine. The L2 pattern-detection framework in `trading/oil/reflect.py` is already well-structured for extension.

---

## What replaced it

- **Sub-6 L2**: `daemon/iterators/oil_botpattern_reflect.py` + `trading/oil/reflect.py`
- **Telegram surface**: `/selftuneproposals`, `/selftuneapprove`, `/selftunereject`
- **Spec**: `docs/plans/OIL_BOT_PATTERN_06_SELF_TUNE_HARNESS.md`
