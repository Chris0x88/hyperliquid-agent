---
kind: agent_tool
last_regenerated: 2026-04-09 16:05
tool_name: trade_journal
tags:
  - agent-tool
---
# Agent Tool: `trade_journal`

**Source**: [`cli/agent_tools.py`](../../cli/agent_tools.py) `TOOL_DEFS`

## Description

Get recent trade history and journal entries. Hard-capped at 25 per call (NORTH_STAR P10).

## Parameters schema

```python
{'type': 'object', 'properties': {'limit': {'type': 'integer', 'description': 'Max entries to return (1-25). Default 10.', 'default': 10, 'minimum': 1, 'maximum': 25}}}
```

## Retrieval bounds

Per NORTH_STAR P10 / MASTER_PLAN Critical Rule 11, every tool that reaches an agent prompt must have hard bounds on what it returns. Check `_tool_trade_journal()` in `cli/agent_tools.py` for the clamp logic; bounded tools are pinned by tests in `tests/test_agent_tools_p10_bounds.py`.

## See also

- Agent runtime: `cli/agent_runtime.py` (injects LIVE CONTEXT + lessons section)
- Tool dispatcher: `cli/agent_tools.py:_TOOL_DISPATCH`
- P10 bounds: [[Data-Discipline|Data Discipline (P10)]]

## Human notes

<!-- HUMAN:BEGIN -->
_Add hand-written context here._
<!-- HUMAN:END -->
