#!/bin/bash
# Start Mission Control: FastAPI backend + Next.js dashboard + Astro docs
# Called by com.hyperliquid.web launchd plist or manually

DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$DIR"

export PATH="$HOME/.bun/bin:$DIR/.venv/bin:/usr/local/bin:/usr/bin:/bin"
export HOME="${HOME:-/Users/cdi}"

# Kill any existing processes on our ports
lsof -ti:8420 | xargs kill -9 2>/dev/null
lsof -ti:3000 | xargs kill -9 2>/dev/null
lsof -ti:4321 | xargs kill -9 2>/dev/null
sleep 1

echo "$(date) Starting Mission Control..."

# 1. FastAPI backend
.venv/bin/uvicorn web.api.app:create_app --factory --host 127.0.0.1 --port 8420 &
BACKEND_PID=$!
echo "  Backend: PID $BACKEND_PID (port 8420)"

# 2. Next.js dashboard (always production build to avoid stale dev cache)
cd web/dashboard
rm -rf .next 2>/dev/null
bun run build 2>&1 | tail -5
bun run start -- -p 3000 -H 127.0.0.1 &
DASH_PID=$!
echo "  Dashboard: PID $DASH_PID (port 3000)"

# 3. Astro docs site (serve pre-built static files)
cd ../docs
if [ -d "dist" ]; then
    bunx serve dist -l 4321 -s 2>/dev/null &
else
    echo "  Docs: dist/ not found — run 'cd web/docs && bun run build' first"
fi
DOCS_PID=$!
echo "  Docs: PID $DOCS_PID (port 4321)"

cd "$DIR"
echo "$(date) Mission Control started."

# Wait for any child to exit
wait
