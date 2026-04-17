# Agent Control Contract — pi-mono-inspired

Locked surface that all agent-control changes target. DO NOT drift from this
without updating every dependent stream.

## State file

`data/agent/state.json` — atomic write on every transition. Schema:

```json
{
  "is_running": true,
  "session_id": "uuid",
  "started_at": "iso8601",
  "current_turn": 3,
  "current_tool": { "name": "edit_file", "args_summary": "...", "started_at": "iso" },
  "abort_flag": false,
  "abort_reason": null,
  "steering_queue": [{"text": "...", "queued_at": "iso"}],
  "follow_up_queue": [{"text": "...", "queued_at": "iso"}],
  "turn_timeout_s": 60,
  "tokens_used_session": 12345,
  "tokens_budget_session": 200000,
  "last_event": {"type": "tool_execution_start", "ts": "iso", "data": {}}
}
```

## Runtime methods (added to agent/runtime.py)

```python
class AgentControl:
    def abort(self, reason: str = "user_requested") -> None: ...
    def is_aborted(self) -> bool: ...
    def steer(self, message: str) -> None: ...
    def follow_up(self, message: str) -> None: ...
    def clear_steering_queue(self) -> None: ...
    def clear_follow_up_queue(self) -> None: ...
    def clear_all_queues(self) -> None: ...
    def get_state(self) -> dict: ...
    def set_state(self, **kwargs) -> None: ...  # atomic state-file write
```

## Hook surface (gates)

```python
class GateDecision:
    allow: bool
    block_reason: Optional[str]
    requires_approval: bool
    transformed_args: Optional[dict]
```

`gate_chain.evaluate(tool_name, args, ctx) -> GateDecision`

## API endpoints

```
POST /api/agent/abort       { "reason": "..." }
POST /api/agent/steer       { "message": "..." }
POST /api/agent/follow-up   { "message": "..." }
POST /api/agent/clear-queues
GET  /api/agent/state       returns the state file contents
```

## Telegram commands (DETERMINISTIC — NO AI CALLS)

- `/stop`     — abort current run
- `/steer <msg>` — inject steering message
- `/cancel`   — clear pending approvals AND abort
- `/follow <msg>` — queue follow-up
- `/agentstate`  — print current state file
