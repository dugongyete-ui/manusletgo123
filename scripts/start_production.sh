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

echo "Starting backend API on port 5000..."
cd /home/runner/workspace/backend
exec python3 -m uvicorn app.main:app \
    --host 0.0.0.0 \
    --port 5000 \
    --log-level info \
    --no-access-log
