#!/bin/bash
set -e

echo "=== Production startup ==="

# Install supervisor and websockify if missing
if ! command -v supervisord &>/dev/null; then
    echo "Installing supervisor..."
    pip install supervisor websockify --quiet
fi

if ! command -v websockify &>/dev/null; then
    echo "Installing websockify..."
    pip install websockify --quiet
fi

SUPERVISORD_BIN=$(python3 -c "import site, os; dirs = site.getsitepackages() + [site.getusersitepackages()]; [print(os.path.join(d, '../../bin/supervisord')) for d in dirs if os.path.exists(os.path.join(d, '../../bin/supervisord'))]" 2>/dev/null | head -1)
SUPERVISORD_BIN=${SUPERVISORD_BIN:-$(which supervisord 2>/dev/null)}

if [ -z "$SUPERVISORD_BIN" ]; then
    echo "ERROR: supervisord not found after install"
    exit 1
fi

echo "Starting sandbox services via supervisord..."
"$SUPERVISORD_BIN" -c /home/runner/workspace/sandbox/replit_supervisord.conf &
SUPERVISOR_PID=$!

echo "Waiting for sandbox API to be ready..."
for i in $(seq 1 30); do
    if curl -sf http://localhost:8080/api/v1/supervisor/status >/dev/null 2>&1; then
        echo "Sandbox API ready after ${i}s"
        break
    fi
    sleep 1
done

echo "Starting backend API..."
exec python3 -m uvicorn app.main:app --host 0.0.0.0 --port 5000
