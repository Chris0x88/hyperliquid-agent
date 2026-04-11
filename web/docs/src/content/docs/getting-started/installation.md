---
title: Installation
description: Set up HyperLiquid Bot from scratch — Python 3.13, Bun, key management, and component startup.
---

import { Aside, Steps } from '@astrojs/starlight/components';

## Prerequisites

- **macOS** (Keychain integration; Linux support is partial)
- **Python 3.13** — `python3.13 --version`
- **Bun** — for the web dashboard and docs site (`curl -fsSL https://bun.sh/install | bash`)
- **A HyperLiquid account** with an API wallet (NOT your main private key)
- **A Telegram bot** — create one via [@BotFather](https://t.me/BotFather)
- **OpenRouter API key** (optional, for AI agent features — session token, not API key)

<Aside type="caution" title="Session tokens only">
Never use API keys for OpenRouter — session tokens only. API costs would be ruinous. The bot uses session tokens exclusively.
</Aside>

<Aside type="caution" title="Never use your main private key">
Use an API wallet. HyperLiquid API wallets can trade but **cannot withdraw funds**. If your key is compromised, revoke it instantly — attackers cannot steal your balance.
</Aside>

---

## Step-by-Step Setup

<Steps>

1. **Clone and install**

   ```bash
   git clone https://github.com/Chris0x88/hyperliquid-agent.git
   cd hyperliquid-agent/agent-cli
   python3.13 -m venv .venv && source .venv/bin/activate
   pip install -e .
   ```

2. **Create an API wallet on HyperLiquid**

   1. Log in at [app.hyperliquid.xyz](https://app.hyperliquid.xyz/)
   2. Go to **Portfolio > API Wallets > Generate**
   3. Name it (e.g., `agent-bot`) and copy the private key immediately
   4. Import it into the encrypted keystore:

   ```bash
   python -m cli.main keys import
   ```

   The key is stored in both the Open Wallet Standard vault (AES-256-GCM) and macOS Keychain — dual-write for resilience.

3. **Configure environment**

   ```bash
   cp .env.example .env
   ```

   Open `.env` and fill in:

   | Variable | Description |
   |----------|-------------|
   | `TELEGRAM_BOT_TOKEN` | From @BotFather |
   | `TELEGRAM_CHAT_ID` | Your chat ID (use @userinfobot to find it) |
   | `HL_WALLET_ADDRESS` | Your HyperLiquid vault/main address |
   | `OPENROUTER_API_KEY` | Optional — session token for AI agent features |

4. **Start the Telegram bot**

   ```bash
   python -m cli.telegram_bot
   ```

   Send `/status` to your bot in Telegram. You should see your current positions and account state.

5. **Start the daemon in WATCH mode**

   ```bash
   python -m cli.main daemon start --tier watch
   ```

   WATCH tier runs all 42 monitoring iterators but gates any autonomous trade placement. Verify it's working with `/health` and `/readiness` in Telegram.

6. **(Optional) Start the web dashboard**

   ```bash
   # Backend API (from agent-cli/)
   .venv/bin/uvicorn web.api.app:create_app --factory --host 127.0.0.1 --port 8420

   # Frontend (from agent-cli/web/dashboard/)
   bun install && bun run dev

   # Docs (from agent-cli/web/docs/)
   bun install && bun run dev
   ```

   Dashboard at `http://localhost:3000`, API at `http://localhost:8420`, docs at `http://localhost:4321`. All bound to localhost only.

7. **(Optional) Set up launchd for automatic start**

   Create your own plist files in `~/Library/LaunchAgents/` to run the daemon and Telegram bot as background services. The repo does not ship plist files — configure them for your environment.

</Steps>

---

## Verifying the Install

Run the test suite:

```bash
cd agent-cli
.venv/bin/python -m pytest tests/ -x -q
```

All tests should pass. If you see failures, check that `.env` has the required variables.

---

## Directory Layout

```
agent-cli/
├── .venv/                  # Python 3.13 virtual environment
├── cli/
│   ├── telegram_bot.py     # Telegram dashboard (slash commands + AI chat)
│   ├── agent_runtime.py    # Embedded Claude agent
│   └── daemon/
│       └── iterators/      # 42 daemon iterators
├── common/                 # Shared libraries (exchange client, utils)
├── parent/                 # Exchange proxy + risk manager
├── modules/                # REFLECT, GUARD, RADAR, etc.
├── data/
│   ├── thesis/             # Thesis JSON files (e.g., xyz_brentoil_state.json)
│   ├── memory/             # memory.db + backups
│   ├── candles/            # candles.db (candle cache)
│   ├── config/             # markets.yaml, kill switches
│   └── agent_memory/       # MEMORY.md (agent memory, flat structure)
├── agent/
│   ├── AGENT.md            # Agent system prompt
│   └── SOUL.md             # Agent personality + trading rules
├── web/
│   ├── api/                # FastAPI backend (port 8420)
│   ├── dashboard/          # Next.js frontend (port 3000)
│   └── docs/               # Astro Starlight docs (port 4321)
└── .env                    # Your secrets (NEVER commit this)
```

---

## Key Management

All key storage dual-writes to two locations for resilience:

1. **OWS vault** — encrypted with AES-256-GCM, accessed via the CLI
2. **macOS Keychain** — accessible via `python -m cli.main keys list`

To rotate a key:

```bash
python -m cli.main keys import   # adds new key
python -m cli.main keys remove <old-key-name>
```

Both stores are updated atomically. If one fails, the operation rolls back.
