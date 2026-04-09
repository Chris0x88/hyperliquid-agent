---
kind: agent_tool
last_regenerated: 2026-04-09 16:05
tool_name: search_lessons
tags:
  - agent-tool
---
# Agent Tool: `search_lessons`

**Source**: [`cli/agent_tools.py`](../../cli/agent_tools.py) `TOOL_DEFS`

## Description

BM25-ranked search over your trade-lesson corpus (verbatim post-mortems of closed trades written after each position closes). Use this BEFORE opening a new position to check whether you've traded a similar setup before and what happened — the lesson summaries are injected automatically at decision time, but this tool lets you drill in with specific queries. Empty query returns most-recent lessons ordered by trade_closed_at. Non-empty query uses FTS5 over summary + body_full + tags, ranked by BM25. Results exclude lessons Chris rejected (reviewed_by_chris = -1) unless include_rejected=True (useful for anti-pattern search). Returns lesson id, market, direction, outcome, ROE%, summary. Use get_lesson(id) to read the verbatim body.

## Parameters schema

```python
{'type': 'object', 'properties': {'query': {'type': 'string', 'description': 'Keyword search over summary/body/tags. Empty string returns recent lessons by date.', 'default': ''}, 'market': {'type': 'string', 'description': "Optional market filter, e.g. 'xyz:BRENTOIL', 'BTC'."}, 'direction': {'type': 'string', 'description': "Optional direction filter: 'long', 'short', or 'flat'.", 'enum': ['long', 'short', 'flat']}, 'signal_source': {'type': 'string', 'description': "Optional signal source filter: 'thesis_driven', 'radar', 'pulse_signal', 'pulse_immediate', 'manual'."}, 'lesson_type': {'type': 'string', 'description': 'Optional lesson type filter.', 'enum': ['sizing', 'entry_timing', 'exit_quality', 'thesis_invalidation', 'funding_carry', 'catalyst_timing', 'pattern_recognition']}, 'outcome': {'type': 'string', 'description': 'Optional outcome filter.', 'enum': ['win', 'loss', 'breakeven', 'scratched']}, 'include_rejected': {'type': 'boolean', 'description': 'If true, include lessons Chris rejected. Defaults to false — rejected lessons are hidden from ranking.', 'default': False}, 'limit': {'type': 'integer', 'description': 'Max results (1-20). Default 5. Hard-capped per NORTH_STAR P10.', 'default': 5, 'minimum': 1, 'maximum': 20}}}
```

## Retrieval bounds

Per NORTH_STAR P10 / MASTER_PLAN Critical Rule 11, every tool that reaches an agent prompt must have hard bounds on what it returns. Check `_tool_search_lessons()` in `cli/agent_tools.py` for the clamp logic; bounded tools are pinned by tests in `tests/test_agent_tools_p10_bounds.py`.

## See also

- Agent runtime: `cli/agent_runtime.py` (injects LIVE CONTEXT + lessons section)
- Tool dispatcher: `cli/agent_tools.py:_TOOL_DISPATCH`
- P10 bounds: [[Data-Discipline|Data Discipline (P10)]]

## Human notes

<!-- HUMAN:BEGIN -->
_Add hand-written context here._
<!-- HUMAN:END -->
