---
kind: agent_tool
last_regenerated: 2026-04-09 14:08
tool_name: get_signals
tags:
  - agent-tool
---
# Agent Tool: `get_signals`

**Source**: [`cli/agent_tools.py`](../../cli/agent_tools.py) `TOOL_DEFS`

## Description

Get recent Pulse (capital inflow) and Radar (opportunity scanner) trade signals. Hard-capped at 50 per call (NORTH_STAR P10).

## Parameters schema

```python
{'type': 'object', 'properties': {'limit': {'type': 'integer', 'description': 'Max signals to return (1-50). Default 20.', 'default': 20, 'minimum': 1, 'maximum': 50}, 'source': {'type': 'string', 'enum': ['all', 'pulse', 'radar'], 'description': 'Filter by signal source', 'default': 'all'}}}
```

## Retrieval bounds

Per NORTH_STAR P10 / MASTER_PLAN Critical Rule 11, every tool that reaches an agent prompt must have hard bounds on what it returns. Check `_tool_get_signals()` in `cli/agent_tools.py` for the clamp logic; bounded tools are pinned by tests in `tests/test_agent_tools_p10_bounds.py`.

## See also

- Agent runtime: `cli/agent_runtime.py` (injects LIVE CONTEXT + lessons section)
- Tool dispatcher: `cli/agent_tools.py:_TOOL_DISPATCH`
- P10 bounds: [[Data-Discipline|Data Discipline (P10)]]

## Human notes

<!-- HUMAN:BEGIN -->
_Add hand-written context here._
<!-- HUMAN:END -->
