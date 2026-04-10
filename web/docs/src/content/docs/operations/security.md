---
title: Security
description: Key management, API wallet setup, session token authentication, and the no-withdrawal guarantee.
---

import { Aside } from '@astrojs/starlight/components';

## The No-Withdrawal Guarantee

<Aside type="tip" title="Your funds are safe even if the key leaks">
HyperLiquid API wallets can trade but **cannot withdraw funds**. If your API key is compromised, attackers can place trades but cannot steal your balance. Revoke the key instantly from the HyperLiquid web UI.
</Aside>

This is by design. The system only ever touches API wallets — never the main wallet private key.

---

## Key Management Architecture

All private key storage uses dual-write for resilience:

1. **OWS vault** — `agent-cli/data/keys/` encrypted with AES-256-GCM
2. **macOS Keychain** — accessible via standard Keychain API

Both copies are kept in sync. If one fails, the other is the fallback.

```bash
# Import a new key
python -m cli.main keys import

# List stored keys
python -m cli.main keys list

# Remove a key
python -m cli.main keys remove <key-name>
```

---

## AI Agent Authentication

<Aside type="danger" title="Session tokens only — never API keys">
The embedded agent uses Anthropic **session tokens**, not API keys. API keys cost money per token. Session tokens are free (same as claude.ai web). Using API keys would accumulate significant costs. This is a non-negotiable rule.
</Aside>

Session tokens are stored in:
```
~/.openclaw/agents/default/agent/auth-profiles.json
```

### Obtaining a Session Token

1. Log in to [claude.ai](https://claude.ai) in your browser
2. Open browser DevTools → Application → Cookies
3. Find the `sessionKey` cookie value
4. Store it in `auth-profiles.json` under the `anthropic` profile

Session tokens expire. When the AI agent starts returning auth errors, the token needs rotation. Run `/models` in Telegram to check if the agent is responding.

### Rotating a Session Token

1. Log into claude.ai in a fresh browser session
2. Extract the new `sessionKey` cookie value
3. Update `auth-profiles.json`
4. Restart the Telegram bot process

---

## OpenRouter Configuration

OpenRouter is used as the model router for some AI features:

```bash
# In .env
OPENROUTER_API_KEY=sk-or-...
```

OpenRouter keys are optional — the system falls back gracefully if not configured. AI agent features won't work without a valid auth source (session token or OpenRouter key).

---

## Environment File (.env)

The `.env` file contains secrets and must never be committed to git:

```
TELEGRAM_BOT_TOKEN=<from @BotFather>
TELEGRAM_CHAT_ID=<your chat ID>
OPENROUTER_API_KEY=<optional>
HL_WALLET_ADDRESS=<your vault/main address>
```

The `.gitignore` excludes `.env` by default. Verify before any commit:

```bash
git status  # .env should never appear as a modified/staged file
```

---

## No External Parties

The system has zero external party dependencies in the trading path:

- No Nunchi
- No builder fees
- No telemetry
- No external party code in the risk management path

All data flows stay within: your machine → HyperLiquid API → your machine.

---

## OpenClaw Boundary

The `~/.openclaw/` directory is a broader AI agent ecosystem that contains multiple agents and configurations beyond this project.

**Never modify:**
- `~/.openclaw/openclaw.json`
- `~/.openclaw/exec-approvals.json`
- Any global OpenClaw config

The only file outside the project directory that may be touched is `~/.openclaw/agents/default/agent/auth-profiles.json` — only for credential sync.
