"""telegram/commands/prompt_templates.py — /templates and /save handlers.

/templates — list all prompt templates in data/agent/prompts/.
/save <name> — save the last user-typed message as a new template.

These are deterministic slash commands (no AI). They take precedence over any
template file with the same name (see _BUILTIN_NAMES in prompts_lib.py).
"""

from __future__ import annotations

import logging

log = logging.getLogger("telegram_bot")


def cmd_templates(token: str, chat_id: str, _args: str) -> None:
    """List all available prompt templates with name + first-line description."""
    from telegram.api import tg_send
    from agent.prompts_lib import list_templates

    templates = list_templates()
    if not templates:
        tg_send(token, chat_id,
            "No prompt templates found.\n\n"
            "Create `.md` files in `data/agent/prompts/` or use "
            "`/save <name>` to capture a message as a template.")
        return

    lines = ["*Prompt Templates*\n"]
    for tmpl in templates:
        vars_hint = ""
        if tmpl.variables:
            vars_hint = f" `[{', '.join('{' + v + '}' for v in tmpl.variables)}]`"
        lines.append(f"  `/{tmpl.name}`{vars_hint} — {tmpl.description}")

    lines.append("")
    lines.append("_Type `/<name>` to expand. Add text after the command to populate `{{args}}`._")
    lines.append("_Use `/save <name>` to capture your last message as a new template._")

    tg_send(token, chat_id, "\n".join(lines))


def cmd_save(token: str, chat_id: str, args: str) -> None:
    """Save the provided text as a new prompt template.

    Usage: /save <name> <body text>

    If only a name is given with no body, a placeholder template is created
    with instructions to edit it in data/agent/prompts/<name>.md.
    """
    from telegram.api import tg_send
    from agent.prompts_lib import save_template

    parts = args.strip().split(None, 1)
    if not parts:
        tg_send(token, chat_id,
            "*Usage:* `/save <name> <prompt body>`\n\n"
            "Example: `/save oilsweep Check oil fundametals and funding rate now.`\n\n"
            "Name rules: lowercase letters, digits, hyphens, underscores only. "
            "Cannot shadow a built-in command.")
        return

    name = parts[0].lower()
    body = parts[1].strip() if len(parts) > 1 else ""

    if not body:
        body = (
            f"{name} — custom operator template.\n"
            "<!-- Edit this file to add your prompt body. -->\n"
            "<!-- Use {{args}} to capture text typed after the command. -->\n\n"
            f"Custom prompt: {{{{args}}}}"
        )

    try:
        path = save_template(name, body)
        # Count chars for feedback
        tg_send(token, chat_id,
            f"*Saved* `/{name}` ({len(body)} chars)\n\n"
            f"File: `{path}`\n\n"
            f"Type `/{name}` to expand it, or `/{name} extra context` to populate `{{args}}`.")
        log.info("Saved template /%s (%d chars) → %s", name, len(body), path)
    except ValueError as e:
        tg_send(token, chat_id, f"Cannot save template: {e}")
    except OSError as e:
        tg_send(token, chat_id, f"Write error saving template `{name}`: {e}")
        log.error("save_template OSError: %s", e)
