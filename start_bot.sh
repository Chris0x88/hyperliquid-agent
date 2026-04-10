#!/bin/bash
.venv/bin/python -m cli.telegram_bot >> telegram_bot.log 2>&1 &
