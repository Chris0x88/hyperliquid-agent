---
title: Security
description: No-withdrawal guarantee, session token authentication, key management, and the OpenClaw boundary.
---

import { Aside } from '@astrojs/starlight/components';

## The No-Withdrawal Guarantee

<Aside type="tip" title="Your funds are safe even if the key leaks">
HyperLiquid API wallets can trade but **cannot withdraw funds**. If your API wallet key is compromised, attackers can place trades but cannot steal your balance. Revoke the key instantly from the HyperLiquid web UI.
</Aside>

This is by design. The system only ever touches API wallets — never the main wallet private key.

---

## Key Management

<Aside type="caution" title="Session tokens ONLY — never API keys">
The embedded AI agent uses Anthropic **session tokens**, not API keys. API keys cost money per token and would accumulate significant costs. Session tokens are free (same as the claude.ai web interface). This is a non-negotiable rule.
</Aside>

### Dual-Write Architecture

All key and credential storage uses dual-write for resilience:

1. **OWS vault** — encrypted credential store
2. **macOS Keychain** — accessible via standard Keychain API

Both copies are kept in sync. If one fails, the other is the fallback. All key storage operations MUST dual-write to both stores.

### Session Token Workflow

Session tokens are stored in:
```
~/.openclaw/agents/default/agent/auth-profiles.json
```

**Obtaining a session token:**
1. Log in to claude.ai in your browser
2. Open browser DevTools, then Application, then Cookies
3. Find the `sessionKey` cookie value
4. Store it in `auth-profiles.json` under the `anthropic` profile

**Rotating a session token** (when the agent starts returning auth errors):
1. Log into claude.ai in a fresh browser session
2. Extract the new `sessionKey` cookie value
3. Update `auth-profiles.json`
4. Restart the Telegram bot process
5. Verify with `/models` in Telegram

---

## OpenRouter Configuration

OpenRouter is used as the model router for some AI features:

```
# In .env
OPENROUTER_API_KEY=sk-or-...
```

OpenRouter keys are optional — the system falls back gracefully if not configured.

---

## Environment Variables

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

All data flows stay within: your machine, HyperLiquid API, your machine.

---

## OpenClaw Boundary

The `~/.openclaw/` directory is the user's entire AI agent ecosystem — it contains multiple agents, bots, and a company of AI workers beyond this project.

**Never modify:**
- `~/.openclaw/openclaw.json`
- `~/.openclaw/exec-approvals.json`
- Any global OpenClaw config

The only file outside the project directory that may be touched is:
```
~/.openclaw/agents/default/agent/auth-profiles.json
```
And only for credential sync.

---

## AI Agent Model Routing

The system uses a tiered model approach:

- **Premium models** (Claude Opus/Sonnet): Judgment calls, thesis analysis, challenging user thesis
- **Mechanical models** (Haiku): Routine tasks, formatting, data extraction

Model routing configuration lives in `data/config/model_config.json`. Free session token credits are temporary — local AI integration is planned for mechanical tasks.
