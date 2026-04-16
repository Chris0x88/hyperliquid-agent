"""telegram.commands — incremental split of the telegram_bot.py monolith.

The 4,200+ line cli/telegram_bot.py is being incrementally decomposed into
cohesive submodules, one group of related commands per file. The HANDLERS
dict in telegram_bot.py still owns the dispatch table; submodules just
host the cmd_* handler implementations.

Convention:
- Each submodule defines `def cmd_*(token, chat_id, args) -> None` handlers
- Submodules avoid circular imports with telegram_bot by lazy-importing
  helpers (`tg_send`, etc.) inside each function
- New handlers ship in their submodule, never in telegram_bot.py
- The 5-surface checklist (handler + HANDLERS dict + _set_telegram_commands
  + cmd_help + cmd_guide) still applies — this refactor just splits where
  the handler bodies live

First wedge: lessons.py (4 handlers, 2026-04-09)
"""
