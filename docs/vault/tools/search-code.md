---
kind: agent_tool
last_regenerated: 2026-04-09 16:36
tool_name: search_code
tags:
  - agent-tool
---
# Agent Tool: `search_code`

**Source**: [`cli/agent_tools.py`](../../cli/agent_tools.py) `TOOL_DEFS`

## Description

Search the codebase for a pattern (grep). Returns matching lines with file:line format.

## Parameters schema

```python
{'type': 'object', 'properties': {'pattern': {'type': 'string', 'description': 'Search pattern (regex supported)'}, 'path': {'type': 'string', 'description': 'Directory to search in, relative to project root', 'default': '.'}}, 'required': ['pattern']}
```

## Retrieval bounds

Per NORTH_STAR P10 / MASTER_PLAN Critical Rule 11, every tool that reaches an agent prompt must have hard bounds on what it returns. Check `_tool_search_code()` in `cli/agent_tools.py` for the clamp logic; bounded tools are pinned by tests in `tests/test_agent_tools_p10_bounds.py`.

## See also

- Agent runtime: `cli/agent_runtime.py` (injects LIVE CONTEXT + lessons section)
- Tool dispatcher: `cli/agent_tools.py:_TOOL_DISPATCH`
- P10 bounds: [[Data-Discipline|Data Discipline (P10)]]

## Human notes

<!-- HUMAN:BEGIN -->
_Add hand-written context here._
<!-- HUMAN:END -->
