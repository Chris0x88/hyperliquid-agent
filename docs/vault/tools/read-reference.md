---
kind: agent_tool
last_regenerated: 2026-04-09 16:36
tool_name: read_reference
tags:
  - agent-tool
---
# Agent Tool: `read_reference`

**Source**: [`cli/agent_tools.py`](../../cli/agent_tools.py) `TOOL_DEFS`

## Description

Read one of your built-in reference docs at agent/reference/<topic>.md. Topics: 'tools' (every tool, when to use it, failure modes), 'architecture' (what runs where, file roles), 'workflows' (how to think about a trade, verify execution, handle failures), 'rules' (current trading rules and constraints). Use these when you need depth that the always-loaded prompt does not carry.

## Parameters schema

```python
{'type': 'object', 'properties': {'topic': {'type': 'string', 'enum': ['tools', 'architecture', 'workflows', 'rules']}}, 'required': ['topic']}
```

## Retrieval bounds

Per NORTH_STAR P10 / MASTER_PLAN Critical Rule 11, every tool that reaches an agent prompt must have hard bounds on what it returns. Check `_tool_read_reference()` in `cli/agent_tools.py` for the clamp logic; bounded tools are pinned by tests in `tests/test_agent_tools_p10_bounds.py`.

## See also

- Agent runtime: `cli/agent_runtime.py` (injects LIVE CONTEXT + lessons section)
- Tool dispatcher: `cli/agent_tools.py:_TOOL_DISPATCH`
- P10 bounds: [[Data-Discipline|Data Discipline (P10)]]

## Human notes

<!-- HUMAN:BEGIN -->
_Add hand-written context here._
<!-- HUMAN:END -->
