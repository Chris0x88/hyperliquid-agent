---
kind: agent_tool
last_regenerated: 2026-04-09 14:08
tool_name: update_thesis
tags:
  - agent-tool
---
# Agent Tool: `update_thesis`

**Source**: [`cli/agent_tools.py`](../../cli/agent_tools.py) `TOOL_DEFS`

## Description

Update thesis conviction and direction for a market. REQUIRES USER APPROVAL.

## Parameters schema

```python
{'type': 'object', 'properties': {'market': {'type': 'string', 'description': "Market, e.g. 'xyz:BRENTOIL'"}, 'direction': {'type': 'string', 'enum': ['long', 'short', 'flat']}, 'conviction': {'type': 'number', 'description': '0.0 to 1.0'}, 'summary': {'type': 'string', 'description': 'Brief thesis summary'}}, 'required': ['market', 'direction', 'conviction']}
```

## Retrieval bounds

Per NORTH_STAR P10 / MASTER_PLAN Critical Rule 11, every tool that reaches an agent prompt must have hard bounds on what it returns. Check `_tool_update_thesis()` in `cli/agent_tools.py` for the clamp logic; bounded tools are pinned by tests in `tests/test_agent_tools_p10_bounds.py`.

## See also

- Agent runtime: `cli/agent_runtime.py` (injects LIVE CONTEXT + lessons section)
- Tool dispatcher: `cli/agent_tools.py:_TOOL_DISPATCH`
- P10 bounds: [[Data-Discipline|Data Discipline (P10)]]

## Human notes

<!-- HUMAN:BEGIN -->
_Add hand-written context here._
<!-- HUMAN:END -->
