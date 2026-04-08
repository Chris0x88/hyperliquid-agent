"""Fake telegram_bot.py for cartographer tests."""


def cmd_hello(token, chat_id, args):
    return "hi"


def cmd_goodbye(token, chat_id, args):
    return "bye"


def cmd_orphan(token, chat_id, args):
    """This one is NOT in HANDLERS — should be flagged."""
    return "orphaned"


HANDLERS = {
    "/hello": cmd_hello,
    "hello": cmd_hello,
    "/goodbye": cmd_goodbye,
    "goodbye": cmd_goodbye,
}


def _set_telegram_commands():
    return [
        {"command": "hello", "description": "Say hello"},
        {"command": "goodbye", "description": "Say goodbye"},
    ]


def cmd_help(token, chat_id, args):
    return "/hello  — Say hello\n/goodbye — Say goodbye"


def cmd_guide(token, chat_id, args):
    return "Guide text: use /hello and /goodbye"
