---
kind: adr
last_regenerated: 2026-04-09 16:36
adr_file: docs/wiki/decisions/010-anthropic-session-token-auth.md
tags:
  - adr
  - decision
---
# ADR-010: Anthropic Session Token Authentication for Telegram Bot

**Source**: [`docs/wiki/decisions/010-anthropic-session-token-auth.md`](../../docs/wiki/decisions/010-anthropic-session-token-auth.md)

## Preview

```
# ADR-010: Anthropic Session Token Authentication for Telegram Bot

**Date:** 2026-04-06
**Status:** In Progress (Sonnet/Opus 429 unresolved)

## Context

The Telegram bot needs to call Anthropic's Messages API using the same session token (OAuth, `session token`) that Claude Code uses. Session tokens are free (tied to subscription, no per-token billing). The bot previously used raw `requests.post()` which failed with 429 on Sonnet/Opus while Haiku worked fine.

Claude Code (which powers OpenClaw) successfully calls Sonnet/Opus/Haiku using the same token. We need to match its implementation exactly.

## Research: How Claude Code Authenticates

Source: Claude Code source (v2.1.87)

```

## Human notes

<!-- HUMAN:BEGIN -->
<!-- HUMAN:END -->
