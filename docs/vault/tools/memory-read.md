---
kind: agent_tool
last_regenerated: 2026-04-09 16:36
tool_name: memory_read
tags:
  - agent-tool
---
# Agent Tool: `memory_read`

**Source**: [`cli/agent_tools.py`](../../cli/agent_tools.py) `TOOL_DEFS`

## Description

Read from agent persistent memory. Use 'index' to see all topics, or specify a topic name.

## Parameters schema

```python
{'type': 'object', 'properties': {'topic': {'type': 'string', 'description': "Topic name or 'index' for the memory index", 'default': 'index'}}}
```

## Retrieval bounds

Per NORTH_STAR P10 / MASTER_PLAN Critical Rule 11, every tool that reaches an agent prompt must have hard bounds on what it returns. Check `_tool_memory_read()` in `cli/agent_tools.py` for the clamp logic; bounded tools are pinned by tests in `tests/test_agent_tools_p10_bounds.py`.

## See also

- Agent runtime: `cli/agent_runtime.py` (injects LIVE CONTEXT + lessons section)
- Tool dispatcher: `cli/agent_tools.py:_TOOL_DISPATCH`
- P10 bounds: [[Data-Discipline|Data Discipline (P10)]]

## Human notes

<!-- HUMAN:BEGIN -->
_Add hand-written context here._
<!-- HUMAN:END -->
