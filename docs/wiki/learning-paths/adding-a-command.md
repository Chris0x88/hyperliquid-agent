# Learning Path: Adding a Telegram Command

Step-by-step guide for adding a new slash command to the Telegram bot.

---

## Step 0: Decide -- deterministic or AI-dependent?

- **Deterministic** (no AI calls, no thesis-file narrative, no AI-seeded text): normal name. Example: `/status`, `/price`, `/orders`.
- **AI-dependent** (calls LLM, consumes thesis narrative, generates natural language): name MUST end in `ai`. Example: `/briefai`, `/brutalreviewai`.

This rule is absolute. See `CLAUDE.md` "Slash Commands vs AI" section.

---

## Step 1: Create the handler function

Signature (always the same):

```python
def cmd_mycommand(token: str, chat_id: str, args: str) -> None:
    """One-line description of what this command does."""
    # args contains everything after the command name
    # Use send(token, chat_id, text) to reply
    pass
```

**Where to put it:**

- Simple commands (<50 lines): add directly to `cli/telegram_bot.py`
- Complex commands (>50 lines): create `cli/telegram_commands/mycommand.py`, import in `telegram_bot.py`

Existing complex command modules for reference:
- `cli/telegram_commands/portfolio.py`
- `cli/telegram_commands/shadow.py`
- `cli/telegram_commands/sim.py`

---

## Step 2: Register in HANDLERS dict

File: `cli/telegram_bot.py`, line ~4337.

Add BOTH the `/command` and bare `command` forms. Add aliases if needed.

```python
HANDLERS = {
    # ... existing handlers ...
    "/mycommand": cmd_mycommand,
    "mycommand": cmd_mycommand,
    "/mc": cmd_mycommand,          # optional short alias
    "mc": cmd_mycommand,
}
```

Every handler key needs both slash and bare forms so that Telegram's menu-tap (sends `/cmd`) and bare typing (sends `cmd`) both work.

---

## Step 3: Add to `_set_telegram_commands()`

File: `cli/telegram_bot.py`, line ~4523.

This registers the command in Telegram's native menu UI (the "/" autocomplete list).

```python
def _set_telegram_commands(token: str) -> None:
    commands = [
        # ... existing commands ...
        {"command": "mycommand", "description": "What it does in 1-5 words"},
    ]
```

Note: if the command is admin-only or rarely used, add it to `_GUARDIAN_MENU_EXEMPT` (line ~4332) instead so it appears in help/guide but not the menu.

---

## Step 4: Add to `cmd_help()`

File: `cli/telegram_bot.py`, line ~961.

Add a one-line entry under the appropriate section. Sections are grouped by function (Portfolio, Trading, Analysis, System, etc).

```python
def cmd_help(token: str, chat_id: str, _args: str) -> None:
    text = (
        # ... existing sections ...
        "/mycommand — What it does\n"
    )
```

---

## Step 5: Add to `cmd_guide()`

File: `cli/telegram_bot.py`, line ~2804.

The guide is the longer-form user manual. Add the command to the relevant section with usage examples.

---

## Step 6: Renderer pattern (if applicable)

If your command output should render differently for Telegram vs AI vs buffer, add it to the `RENDERER_COMMANDS` set (line ~4313):

```python
RENDERER_COMMANDS = {
    cmd_status, cmd_price, cmd_orders, cmd_health, cmd_menu,
    cmd_mycommand,  # <-- add here
}
```

Then implement the command using `common/renderer.py`'s `Renderer` ABC. The tool core lives in `common/tools.py` (shared implementation), with renderers in `common/tool_renderers.py`.

---

## Step 7: Add tests

File: `tests/test_telegram_<feature>_command.py` (e.g., `test_telegram_news_command.py`)

At minimum, test that the handler is registered and callable. For non-trivial logic, test the core behavior.

---

## Step 8: Update docs

Add the new command to `docs/wiki/components/telegram-bot.md` under the appropriate command table.

---

## Complete checklist

```
[ ] Handler function created (cmd_mycommand)
[ ] AI-dependent? -> name ends in 'ai'
[ ] HANDLERS dict: both /mycommand and mycommand (+ aliases)
[ ] _set_telegram_commands(): menu entry (or _GUARDIAN_MENU_EXEMPT)
[ ] cmd_help(): one-line entry under right section
[ ] cmd_guide(): entry with usage examples
[ ] RENDERER_COMMANDS: added if using renderer pattern
[ ] Tests: at least registration test
[ ] Docs: updated telegram-bot.md
```

---

## Example: a minimal read-only command

```python
# In cli/telegram_bot.py

def cmd_uptime(token: str, chat_id: str, _args: str) -> None:
    """Show how long the daemon has been running."""
    from cli.daemon.state import StateStore
    store = StateStore()
    state = store.load()
    if not state:
        send(token, chat_id, "Daemon not running.")
        return
    started = state.get("started_at", 0)
    elapsed = int(time.time()) - started
    hours, remainder = divmod(elapsed, 3600)
    minutes, _ = divmod(remainder, 60)
    send(token, chat_id, f"Daemon uptime: {hours}h {minutes}m")
```

Then register everywhere:
- `HANDLERS`: `/uptime` + `uptime`
- `_set_telegram_commands`: `{"command": "uptime", "description": "Show daemon uptime"}`
- `cmd_help`: `"/uptime -- Show daemon uptime\n"`
- `cmd_guide`: add under System section
