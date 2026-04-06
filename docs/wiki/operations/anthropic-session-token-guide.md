# Anthropic Session Token Authentication — CRITICAL REFERENCE

> **DO NOT DELETE THIS FILE.** It documents hard-won knowledge about how session tokens work with the Anthropic API. This took extensive debugging to figure out.

## THE SOLUTION: Claude CLI Binary Proxy

The Claude Code CLI binary at `~/Library/Application Support/Claude/claude-code/*/claude.app/Contents/MacOS/claude` uses the exact same auth stack as Claude Code desktop. It handles OAuth tokens natively.

```python
import subprocess as sp
result = sp.run(
    [str(cli_path), "--model", "claude-sonnet-4-6",
     "--output-format", "json", "-p", prompt],
    capture_output=True, text=True, timeout=90,
)
data = json.loads(result.stdout)
response_text = data["result"]
```

### Why NOT the Agent SDK

**The Agent SDK does NOT support OAuth tokens.** As of April 2026, Anthropic restricts OAuth session tokens to Claude Code and Claude.ai only. The Agent SDK requires console API keys (`ANTHROPIC_API_KEY`) with pay-per-use billing. We tested this — it returns 401.

See: https://github.com/anthropics/claude-code/issues/6536

### Current Implementation Status

The bot uses the **Claude CLI binary** as a proxy for Sonnet/Opus calls. `_call_via_claude_cli()` in `cli/telegram_agent.py` handles tool injection, conversation history, and response parsing. `_find_claude_cli()` dynamically locates the binary across Claude Code version upgrades.

---

## The Problem (Historical)

Session tokens (OAuth) from Claude.ai subscriptions (Pro/Max) allow free API calls — no per-token billing. But calling the Anthropic Messages API directly with these tokens from Python (via `requests`, `httpx`, or even the official `anthropic` Python SDK) results in **429 errors for Sonnet and Opus models**. Haiku works fine.

The exact same token works perfectly when used through Claude Code / OpenClaw (the desktop app).

## Root Cause

Claude Code is a compiled Bun/JavaScript binary that uses the JavaScript Anthropic SDK. There is something in the JS SDK's connection-level handling — likely HTTP/2 multiplexing, TLS session management, or a server-side session identifier — that the Python SDK cannot replicate. The server rejects Sonnet/Opus calls from Python clients with a 429 that has **no rate-limit headers** (unlike normal rate limits which include `anthropic-ratelimit-unified-*` headers).

This is NOT:
- An expired token (verified with freshly refreshed tokens)
- A rate limit (unified utilization shows 1%, `status: allowed`)
- A missing header (tested every combination of beta flags)
- A wrong auth method (tested SDK `auth_token`, raw Bearer, empty X-Api-Key)
- Concurrent session exhaustion (tested with all other sessions killed)

## The Solution

Use the **Claude Code CLI binary** as an API proxy. The binary at `~/Library/Application Support/Claude/claude-code/*/claude.app/Contents/MacOS/claude` uses the exact same auth stack as OpenClaw.

```python
# Call Sonnet/Opus via CLI binary
result = subprocess.run(
    [str(CLAUDE_CLI_PATH), "--model", "claude-sonnet-4-6",
     "--output-format", "json", "-p", prompt],
    capture_output=True, text=True, timeout=60,
)
data = json.loads(result.stdout)
response_text = data["result"]
```

### Routing Strategy

| Model | Path | Why |
|-------|------|-----|
| Haiku | Python SDK direct (`auth_token=`) | Works fine, free, supports streaming + tools |
| Sonnet | Claude CLI binary | Python SDK gets 429, CLI works |
| Opus | Claude CLI binary | Python SDK gets 429, CLI works |
| Free models | OpenRouter API | Separate API key, user-controlled |

### Limitations of CLI Path

- **No streaming** — CLI returns complete response (no real-time token updates)
- **No tool calling** — CLI doesn't support function calling; tool loops fall back to Haiku via SDK
- **~3-5s overhead** — process spawn + CLI bootstrap adds latency
- **Version pinned** — path includes Claude Code version number (currently 2.1.87)

## Token Lifecycle

### Storage
- **Primary**: macOS Keychain → `Claude Code-credentials` → `claudeAiOauth.accessToken`
- **Secondary**: `~/.openclaw/agents/default/agent/auth-profiles.json`

### TTL & Refresh
- Access tokens expire after **8 hours**
- Refresh via `POST https://platform.claude.com/v1/oauth/token`
- Client ID: `9d1c250a-e61b-44d9-88ed-5944d1962f5e`
- Scopes: `user:profile user:inference user:sessions:claude_code user:mcp_servers user:file_upload`
- The bot auto-refreshes from Keychain on startup and when tokens expire

### Reading Token (Priority Order)
1. macOS Keychain (shared with Claude Code, auto-refreshed)
2. auth-profiles.json (may be stale)
3. `ANTHROPIC_API_KEY` env var

## Headers That Claude Code Sends

### Beta Headers (from `betas.ts`)
```
anthropic-beta: oauth-2025-04-20,claude-code-20250219,interleaved-thinking-2025-05-14,prompt-caching-scope-2026-01-05,token-efficient-tools-2026-03-28
```

| Beta | Purpose |
|------|---------|
| `oauth-2025-04-20` | **Required** for session token auth (401 without it) |
| `claude-code-20250219` | Claude Code feature flag |
| `interleaved-thinking-2025-05-14` | Extended thinking for Sonnet/Opus |
| `prompt-caching-scope-2026-01-05` | Cache scope control |
| `token-efficient-tools-2026-03-28` | ~4.5% output token reduction |

### Other Headers
```
Authorization: Bearer {token}
x-app: cli
user-agent: claude-cli/2.1.87
X-Claude-Code-Session-Id: {uuid}
anthropic-version: 2023-06-01
```

### SDK Auth Difference
The SDK's `auth_token=` param sends BOTH `Authorization: Bearer {token}` AND `X-Api-Key: ` (empty string). Raw HTTP calls without the empty `X-Api-Key` header may behave differently.

## Prompt Caching

Cached tokens don't count against ITPM rate limits. This is critical for session tokens.

### Cache Control
```python
{"type": "ephemeral", "ttl": "1h"}  # for Max/Pro subscribers
```

### What Gets Cached
- System prompt (static — `cache_control` on the text block)
- Tool definitions (last tool gets `cache_control`)
- Last message content block (the `addCacheBreakpoints` pattern)

### What Must NOT Be in System Prompt
- Live context (prices, positions) — changes every call, busts cache
- Move dynamic content to a user message instead

## What We Tried (and Failed)

For posterity — every approach that did NOT work for Sonnet/Opus:

1. Raw `requests.post()` with Bearer auth — 429
2. Raw `requests.post()` with every beta combination — 429
3. `httpx` with HTTP/2 — ImportError (h2 not installed)
4. `curl` with identical headers — 429
5. Official `anthropic` Python SDK with `auth_token=` — 429
6. SDK with `max_retries=5` — still 429 after all retries
7. SDK with metadata (device_id, account_uuid) — 429
8. SDK with `X-Claude-Code-Session-Id` header — 429
9. Fresh token from OAuth refresh endpoint — 429
10. Token from Keychain (same as Claude Code uses) — 429
11. After killing all 15 other Claude Code sessions — 429
12. After 60-second cooldown between calls — 429
13. With `thinking` config enabled — 429
14. With `temperature: 1` — 429
15. With `betas` in request body — 400 (not a valid field)

**Only the Claude CLI binary works.**

## Files

| File | Purpose |
|------|---------|
| `cli/telegram_agent.py` | `_call_via_claude_cli()`, `_call_anthropic()`, `_get_anthropic_key()` |
| `cli/agent_runtime.py` | `stream_and_accumulate()` — streaming SSE (Haiku only) |
| `docs/wiki/decisions/010-anthropic-session-token-auth.md` | ADR with full research |
| `~/.openclaw/agents/default/agent/auth-profiles.json` | Token storage |

## Related ADR

See [ADR-010: Anthropic Session Token Authentication](../decisions/010-anthropic-session-token-auth.md)
