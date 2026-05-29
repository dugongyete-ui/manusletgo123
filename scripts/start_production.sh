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

echo "Starting sandbox services (Xvfb, Chrome, VNC, sandbox API)..."
"$PYTHONLIBS/supervisord" -c /home/runner/workspace/sandbox/replit_supervisord.conf

echo "Waiting for sandbox API to be ready..."
READY=0
for i in $(seq 1 40); do
    if curl -sf http://localhost:8080/api/v1/supervisor/status >/dev/null 2>&1; then
        echo "Sandbox API ready after ${i}s"
        READY=1
        break
    fi
    sleep 1
done

if [ "$READY" -eq 0 ]; then
    echo "WARNING: Sandbox API not ready after 40s — starting backend anyway"
fi

echo "Starting backend API on port 5000..."
cd /home/runner/workspace/backend
exec python3 -m uvicorn app.main:app \
    --host 0.0.0.0 \
    --port 5000 \
    --log-level info \
    --no-access-log
