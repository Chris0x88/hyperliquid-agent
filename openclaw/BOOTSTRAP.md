# BOOTSTRAP.md — First Session Startup

On first session or after restart:

## Step 1: Load Skills
Load the `hyperliquid-research` skill immediately. This gives you access to all research files.

## Step 2: Read Current State
```bash
cat /Users/cdi/Developer/HyperLiquid_Bot/agent-cli/data/research/markets/xyz_brentoil/README.md
tail -3 /Users/cdi/Developer/HyperLiquid_Bot/agent-cli/data/research/markets/xyz_brentoil/signals.jsonl
```

## Step 3: Greet
Tell the user you're online and give a 3-line status:
- Current BRENTOIL position (or FLAT)
- Thesis strength
- Next catalyst

## Step 4: Be Ready
The user will ask about markets. Read files first, answer from data.
