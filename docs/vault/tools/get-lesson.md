---
kind: agent_tool
last_regenerated: 2026-04-09 16:05
tool_name: get_lesson
tags:
  - agent-tool
---
# Agent Tool: `get_lesson`

**Source**: [`cli/agent_tools.py`](../../cli/agent_tools.py) `TOOL_DEFS`

## Description

Fetch a single lesson by id and return its full verbatim body (the entire post-mortem: thesis snapshot at open time, entry reasoning, journal retrospective, autoresearch eval window, news context at open, and your own structured analysis from when you wrote it). Call this after search_lessons when a ranked hit looks relevant and you need the full context, not just the summary.

## Parameters schema

```python
{'type': 'object', 'properties': {'id': {'type': 'integer', 'description': 'Lesson id from search_lessons results.'}}, 'required': ['id']}
```

## Retrieval bounds

Per NORTH_STAR P10 / MASTER_PLAN Critical Rule 11, every tool that reaches an agent prompt must have hard bounds on what it returns. Check `_tool_get_lesson()` in `cli/agent_tools.py` for the clamp logic; bounded tools are pinned by tests in `tests/test_agent_tools_p10_bounds.py`.

## See also

- Agent runtime: `cli/agent_runtime.py` (injects LIVE CONTEXT + lessons section)
- Tool dispatcher: `cli/agent_tools.py:_TOOL_DISPATCH`
- P10 bounds: [[Data-Discipline|Data Discipline (P10)]]

## Human notes

<!-- HUMAN:BEGIN -->
_Add hand-written context here._
<!-- HUMAN:END -->
