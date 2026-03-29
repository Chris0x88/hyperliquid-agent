# Telegram Group Setup Guide

Set up a multi-bot trading group with fixed commands + AI agent chat.

## The Architecture

One Telegram group, two (or three) bots:

| Bot | Role | Credits |
|-----|------|---------|
| **Commands Bot** | /status /chart /watchlist /price /pnl /orders | Free (fixed Python) |
| **OpenClaw Bot** | AI conversation, analysis, strategy discussion | OpenClaw/OpenRouter |
| **Claude Code** (optional) | Hourly monitoring, code improvement, trade execution | Claude subscription |

## Step-by-Step

### 1. Create Two Bots via @BotFather

Open Telegram, message @BotFather:

```
/newbot → HyperLiquid Commands → @YourCommands_bot
/newbot → HyperLiquid Agent → @YourAgent_bot
```

Save both tokens.

### 2. CRITICAL: Disable Privacy Mode for the Agent Bot

Still in @BotFather:
```
/mybots → @YourAgent_bot → Bot Settings → Group Privacy → Turn OFF
```

**Without this, the bot can't read group messages.** This is the #1 reason group chat fails.

### 3. Create a Telegram Group

In Telegram:
1. Create new group → name it (e.g., "HyperLiquid Trading")
2. Add BOTH bots to the group
3. **Important:** After adding the agent bot, **remove and re-add it** — this forces Telegram to apply the privacy mode change

### 4. Get the Group Chat ID

The group has a numeric ID you need for configuration. Two ways to find it:

**Option A:** Check OpenClaw logs after sending a message:
```bash
tail -20 /tmp/openclaw/openclaw-$(date +%Y-%m-%d).log | grep chatId
```

**Option B:** Use the bot API:
```python
import requests
token = "YOUR_AGENT_BOT_TOKEN"
r = requests.get(f"https://api.telegram.org/bot{token}/getUpdates")
for u in r.json()["result"]:
    chat = u.get("message", {}).get("chat", {})
    if chat.get("type") in ("group", "supergroup"):
        print(f"Group: {chat['title']} → ID: {chat['id']}")
```

**Gotcha: Supergroup IDs.** When Telegram upgrades your group to a supergroup (which happens automatically), the ID changes format. You may see TWO IDs:
- `-5272127444` (original group)
- `-1003705745676` (supergroup — this is the active one)

**Add BOTH IDs to your config** to be safe. The supergroup ID is the one that matters for new messages.

### 5. Configure the Commands Bot

Store credentials in macOS Keychain:
```bash
security add-generic-password -s hl-agent-telegram -a bot_token -w "YOUR_COMMANDS_TOKEN" -U
security add-generic-password -s hl-agent-telegram -a chat_id -w "YOUR_CHAT_ID" -U
```

Start the bot:
```bash
hl telegram start
```

### 6. Configure OpenClaw

Add the agent to `~/.openclaw/openclaw.json`:

```json5
{
  agents: {
    list: [
      // ... existing agents ...
      {
        id: "hl-trader",
        name: "HyperLiquid Trader",
        workspace: "/path/to/hyperliquid-agent/openclaw"
      }
    ]
  },
  bindings: [
    {
      agentId: "hl-trader",
      match: { channel: "telegram", accountId: "hl-trader" }
    }
    // ... existing bindings ...
  ],
  channels: {
    telegram: {
      groups: {
        "-YOUR_GROUP_ID": { requireMention: false },
        "-YOUR_SUPERGROUP_ID": { requireMention: false }
      },
      accounts: {
        "hl-trader": {
          botToken: "${OPENCLAW_TG_HLTRADER_TOKEN}",
          dmPolicy: "allowlist",
          allowFrom: ["YOUR_TELEGRAM_USER_ID"],
          groups: {
            "-YOUR_GROUP_ID": { requireMention: false },
            "-YOUR_SUPERGROUP_ID": { requireMention: false }
          },
          groupPolicy: "open",
          groupAllowFrom: ["YOUR_TELEGRAM_USER_ID"],
          streaming: "partial"
        }
      }
    }
  }
}
```

Add the token to `~/.openclaw/.env`:
```
OPENCLAW_TG_HLTRADER_TOKEN=your_agent_bot_token_here
```

Restart the gateway:
```bash
openclaw gateway restart
```

### 7. Verify

In your Telegram group:
- Type `/status` → Commands Bot responds instantly (fixed code)
- Type "How's my portfolio looking?" → OpenClaw Bot responds (AI)
- Type `/chart oil` → Commands Bot sends a chart image

## Common Issues

### Bot doesn't respond in group
1. **Privacy mode still on** — disable in BotFather, then remove and re-add bot to group
2. **Group not in config** — add both group ID AND supergroup ID
3. **`groupAllowFrom` has group IDs** — it should only contain USER IDs. Group IDs go in the `groups` dict
4. **`requireMention: false` missing** — without this, bot only responds when @mentioned
5. **`groupPolicy: "open"` needed** — at the account level for the agent bot

### Two different group IDs
Telegram automatically upgrades groups to supergroups. This changes the ID. Add both to your config. Check logs for the active ID.

### Commands bot responds 3 times
Multiple bot instances running. The bot now auto-kills previous instances on startup, but check: `ps aux | grep telegram_bot`

### OpenClaw says "not-allowed"
The group chat ID is not in the `groups` config at BOTH the top-level AND account-level telegram config. Add it to both.

### OpenClaw responds to slash commands (duplicate responses)
Both bots respond to `/status`, `/help`, etc. Fix:

1. **Disable native commands** on the OpenClaw agent's Telegram account:
   ```json5
   accounts: {
     "hl-trader": {
       commands: { native: false, nativeSkills: false },
       // ... rest of config
     }
   }
   ```

2. **Add to the agent's system prompt** (AGENT.md):
   ```
   NEVER respond to messages starting with "/".
   Slash commands are handled by the Commands Bot.
   ```

3. **In the OpenClaw dashboard**: if there's a "commands" toggle for the channel, disable it.

This ensures slash commands only go to the Commands Bot, and free text only goes to OpenClaw.

### Full checklist for group setup

Do ALL of these or it won't work:

- [ ] Create two bots in @BotFather
- [ ] Disable privacy mode for the AGENT bot (Bot Settings → Group Privacy → OFF)
- [ ] Create the Telegram group
- [ ] Add both bots to the group
- [ ] **Remove and re-add the agent bot** (forces privacy mode change to take effect)
- [ ] Get both group IDs (original AND supergroup — add both to config)
- [ ] Set `requireMention: false` for the group at both top-level AND account-level
- [ ] Set `groupPolicy: "open"` on the agent account
- [ ] Set `commands: {native: false}` on the agent account
- [ ] Add `groupAllowFrom: [YOUR_USER_ID]` (user IDs only, NOT group IDs)
- [ ] Add slash command ignore rule to agent's AGENT.md system prompt
- [ ] Restart the gateway: `openclaw gateway restart`
