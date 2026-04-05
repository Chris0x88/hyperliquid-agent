# OpenRouter Integration — Setup & Maintenance

## Architecture

The Telegram bot uses OpenRouter as the LLM provider for AI chat (free-text messages).
The integration lives in `cli/telegram_agent.py`.

## Critical Requirements

### 1. Required Headers for Free Models

Free models (those with `:free` suffix) **REQUIRE** these headers or they may be
charged at paid rates or silently rejected:

```python
headers = {
    "Authorization": f"Bearer {api_key}",
    "Content-Type": "application/json",
    "HTTP-Referer": "https://openclaw.ai",  # App attribution
    "X-Title": "OpenClaw",                  # App name
}
```

**Never remove these headers.** Without them, OpenRouter cannot attribute usage
to our app and free models stop working.

### 2. Rate Limits

| Tier | RPM | Daily | Notes |
|------|-----|-------|-------|
| Free | 20 | ~200 | Varies by model, can increase with credit purchases |
| Paid | 200+ | Unlimited | Requires credit balance on OpenRouter |

The bot implements retry with exponential backoff for 429 errors:
- 3 retries, base delay 2s, exponential (2s, 4s, 8s)
- If all retries fail, returns a user-friendly message

### 3. API Key

Stored in `~/.openclaw/agents/default/agent/auth-profiles.json` under the
`openrouter:default` profile. Fallback: `OPENROUTER_API_KEY` env var.

**Never hardcode the API key in source code.**

### 4. Model Selection

- Active model stored in `data/config/model_config.json`
- Default fallback: `stepfun/step-3.5-flash:free`
- Users switch via `/models` command (inline keyboard buttons)
- Curated list defined in `_CURATED_MODELS` in `telegram_agent.py`

## Updating the Model List

The curated model list lives in `cli/telegram_agent.py` as `_CURATED_MODELS`.

### When to update
- When new free models appear on OpenRouter
- When existing free models are deprecated
- When the user requests new models

### How to check available free models
```bash
curl -s "https://openrouter.ai/api/v1/models" | python3 -c "
import json, sys
data = json.load(sys.stdin)
free = [m for m in data['data'] if m['id'].endswith(':free')]
for m in sorted(free, key=lambda x: x['id']):
    print(f\"{m['id']:55s} ctx={m.get('context_length', 0)}\")
"
```

### Model entry format
```python
{"id": "provider/model-name:free", "name": "Short Name", "tier": "free"},
```

- `id`: Exact OpenRouter model slug (what gets sent in the API call)
- `name`: Short display name for Telegram buttons (keep under ~15 chars)
- `tier`: `"free"` or `"paid"` — determines which section it appears in

### Rules
1. **Keep names short** — they appear as Telegram inline keyboard buttons
2. **Free models end with `:free`** — this is OpenRouter's convention
3. **Paid models require credit balance** — warn the user in the UI
4. **Test after updating** — switch to the model via `/models` and send a message
5. **Models.json merge** — any models in `~/.openclaw/agents/default/agent/models.json`
   that aren't in the curated list get auto-appended

## Common Issues

### 429 Rate Limited
- Free model rate limits hit. The bot retries 3x with backoff.
- If persistent: user is sending too many messages, or OpenRouter is under load.
- Fix: switch to a paid model, or wait.

### Model not responding
- Check the model is still available: `curl https://openrouter.ai/api/v1/models | grep "model-id"`
- Some free models go offline temporarily. Switch to another.

### API key expired
- Regenerate at https://openrouter.ai/settings/keys
- Update in `~/.openclaw/agents/default/agent/auth-profiles.json`

## Files

| File | Purpose |
|------|---------|
| `cli/telegram_agent.py` | Main integration — `_call_openrouter()`, model list, config |
| `data/config/model_config.json` | Persisted active model selection |
| `~/.openclaw/agents/default/agent/auth-profiles.json` | API key (shared with OpenClaw) |
| `~/.openclaw/agents/default/agent/models.json` | OpenClaw model registry (auto-merged) |
| `cli/telegram_bot.py` | `/models` command handler + inline keyboard |
