#!/bin/bash

echo "=== Production startup ==="

PYTHONLIBS="/home/runner/workspace/.pythonlibs/bin"

# Install supervisor and websockify if missing
if [ ! -f "$PYTHONLIBS/supervisord" ]; then
    echo "Installing supervisor + websockify..."
    pip install supervisor websockify --quiet
fi

# Kill any stale supervisord instance so we start clean
if [ -f /tmp/supervisord.pid ]; then
    OLD_PID=$(cat /tmp/supervisord.pid 2>/dev/null)
    if [ -n "$OLD_PID" ] && kill -0 "$OLD_PID" 2>/dev/null; then
        echo "Stopping stale supervisord (pid $OLD_PID)..."
        kill "$OLD_PID" 2>/dev/null || true
        sleep 1
    fi
    rm -f /tmp/supervisord.pid
fi

echo "Starting sandbox services in background (Xvfb, Chrome, VNC, sandbox API)..."
"$PYTHONLIBS/supervisord" -c /home/runner/workspace/sandbox/replit_supervisord.conf &

# ── Frontend build guard ──────────────────────────────────────────────────────
# uvicorn serves frontend/dist straight from disk and nothing rebuilds it at
# startup. A reprovision/snapshot restore can roll that folder back to an OLD
# build while the source stays new — the chat UI then silently regresses
# (lost collapsible prompts / copy buttons / layout fixes). Rebuild here so
# production always serves a dist that matches the source. Fail-open.
ensure_fresh_dist() {
  REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
  cd "$REPO_ROOT"
  if [ ! -f frontend/dist/index.html ]; then
    echo "[build-guard] frontend/dist missing — building..."
    REBUILD=1
  else
    NEWER_SRC=$(find frontend/src frontend/index.html frontend/package.json \
      frontend/vite.config.ts frontend/vite.config.js \
      -type f -newer frontend/dist/index.html 2>/dev/null | head -n 1)
    if [ -n "$NEWER_SRC" ]; then
      echo "[build-guard] frontend/dist is older than $NEWER_SRC — rebuilding..."
      REBUILD=1
    fi
  fi
  if [ "${REBUILD:-0}" = "1" ]; then
    (cd frontend && (pnpm run build || npm run build)) \
      || echo "[build-guard] WARN: rebuild failed — serving existing dist"
  else
    echo "[build-guard] frontend/dist is fresh — no rebuild needed"
  fi
}
ensure_fresh_dist

echo "Starting backend API on port 5000..."
cd /home/runner/workspace/backend
exec python3 -m uvicorn app.main:app \
    --host 0.0.0.0 \
    --port 5000 \
    --log-level info \
    --no-access-log
