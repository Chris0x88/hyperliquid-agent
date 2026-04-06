# ADR-010: Anthropic Session Token Authentication for Telegram Bot

**Date:** 2026-04-06
**Status:** In Progress (Sonnet/Opus 429 unresolved)

## Context

The Telegram bot needs to call Anthropic's Messages API using the same session token (OAuth, `session token`) that Claude Code uses. Session tokens are free (tied to subscription, no per-token billing). The bot previously used raw `requests.post()` which failed with 429 on Sonnet/Opus while Haiku worked fine.

Claude Code (which powers OpenClaw) successfully calls Sonnet/Opus/Haiku using the same token. We need to match its implementation exactly.

## Research: How Claude Code Authenticates

Source: Claude Code source (v2.1.87)

### Token Lifecycle

1. **Storage**: macOS Keychain entry `Claude Code-credentials` → `claudeAiOauth.accessToken`
2. **TTL**: 8 hours. Refresh token stored alongside.
3. **Refresh**: `POST https://platform.claude.com/v1/oauth/token` with `grant_type=refresh_token`, `client_id=9d1c250a-e61b-44d9-88ed-5944d1962f5e`, scopes: `user:profile user:inference user:sessions:claude_code user:mcp_servers user:file_upload`
4. **Auto-refresh**: `checkAndRefreshOAuthTokenIfNeeded()` called before every client creation (client.ts:132)

### SDK Client Creation (client.ts:301-315)

```typescript
const clientConfig = {
  apiKey: isClaudeAISubscriber() ? null : apiKey,
  authToken: isClaudeAISubscriber() ? oauthToken : undefined,
  defaultHeaders: {
    'x-app': 'cli',
    'User-Agent': getUserAgent(),
    'X-Claude-Code-Session-Id': getSessionId(),
  },
  maxRetries,
  timeout: 600000,
}
return new Anthropic(clientConfig)
```

Key: uses `authToken` (not `apiKey`) for subscribers. The SDK sends `Authorization: Bearer {token}` + `X-Api-Key: ` (empty).

### Beta Headers (betas.ts, assembled in getMergedBetas())

For subscribers with Sonnet/Opus:
- `oauth-2025-04-20` (required for OAuth auth)
- `claude-code-20250219` (Claude Code features)
- `interleaved-thinking-2025-05-14` (thinking for Sonnet/Opus)
- `prompt-caching-scope-2026-01-05` (cache scope control)
- `token-efficient-tools-2026-03-28` (~4.5% output token reduction)

Sent via `anthropic-beta` header (comma-separated).

### Prompt Caching (claude.ts getCacheControl())

```typescript
{ type: 'ephemeral', ttl: '1h' }  // for subscribers
```

Applied to:
- System prompt blocks (`payload.system[].cache_control`)
- Last tool definition (`payload.tools[-1].cache_control`)
- Last message content block (via `addCacheBreakpoints()`)

Cached tokens don't count against ITPM rate limits.

### Request Body (claude.ts:1699-1728)

```typescript
{
  model, messages, system, tools, tool_choice,
  betas: betasParams,              // SDK maps to anthropic-beta header
  metadata: { user_id: JSON.stringify({
    device_id, account_uuid, session_id
  })},
  max_tokens, thinking, temperature,
}
```

### Rate Limit Handling (withRetry.ts:765-769)

```typescript
if (error.status === 429) {
  return !isClaudeAISubscriber() || isEnterpriseSubscriber()
}
```

For Max/Pro subscribers: 429 is NOT retried (treated as hard limit). Only enterprise users retry 429s. Persistent retry (up to 6h) is ant-only via `CLAUDE_CODE_UNATTENDED_RETRY`.

## Decision

### What we implemented

1. **Anthropic Python SDK** (`anthropic.Anthropic`) with `auth_token=` parameter, matching Claude Code's `authToken:` in the JS SDK
2. **Token from Keychain** first (shared with Claude Code), with auto-refresh via OAuth endpoint
3. **Correct beta headers**: oauth, claude-code, thinking, cache-scope, token-efficient-tools
4. **Prompt caching**: 1h TTL ephemeral on system, tools, last message
5. **Live context separated** from system prompt to avoid cache-busting
6. **Shared helpers**: `_convert_messages_to_anthropic()`, `_build_anthropic_payload()`, `_build_anthropic_headers()`, `_parse_anthropic_response()`

### What's still broken

Sonnet/Opus returns 429 (no rate-limit headers, just `x-should-retry: true`) from standalone Python calls even with:
- Fresh token (valid 7+ hours)
- Official Anthropic SDK with `auth_token`
- Identical headers to Claude Code
- All other sessions killed
- 60+ second cooldown between calls
- Metadata with device_id and account_uuid

Haiku works every time. The 429 has no `anthropic-ratelimit-unified-*` headers, unlike normal rate limits which show utilization. This suggests the rejection happens before the rate limiter — possibly a concurrency or session-type restriction.

### Open questions

1. Does the JS SDK (used by Claude Code) negotiate something at the connection level that the Python SDK doesn't? (HTTP/2 multiplexing, TLS session tickets, etc.)
2. Is there a server-side allowlist for Claude Code sessions identified by some combination of headers?
3. Does the `claude-code-20250219` beta grant elevated rate limits that only work when the full Claude Code client stack is present?
4. Is this a temporary account-level throttle from the earlier heavy usage (14 concurrent sessions)?

### Subscription details

- Plan: Max (`default_claude_max_20x` tier)
- Unified rate limit: 1% utilization at time of testing
- `hasExtraUsageEnabled: false`

## Consequences

- Haiku works perfectly via direct API (free)
- Sonnet/Opus fall back to Haiku when 429'd
- The caching, headers, and SDK migration are correct regardless — they'll work when the 429 resolves
- OpenRouter remains available as a paid alternative if needed (user controls this separately)
- Further investigation needed: may require Anthropic support ticket or studying the JS SDK's HTTP-level behavior
