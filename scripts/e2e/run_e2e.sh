#!/bin/bash
# E2E orchestrator — runs the full Replit-like stack in ONE bash session:
#   supervisord (xvfb + chrome + websockify + sandbox API :8080)
#   + backend (:8000)
#   + e2e_driver (register user, create session, send message, stream SSE)
# Everything is cleaned up at the end.
#
# Configuration (all optional):
#   E2E_MESSAGE    message text to send (default: the QA "test all tools" prompt)
#   E2E_TIMEOUT    overall timeout seconds (default: 420)
#   E2E_NEW_SESSION=1   create a fresh chat session instead of reusing
#   E2E_NO_SEND=1       only fetch existing session state, don't send a message
#   E2E_PYTHON     python interpreter for backend/driver (default: $E2E_VENV_BIN/python3, else python3)
#   E2E_VENV_BIN   venv bin dir used inside supervisord (default: $HOME/.venv/bin)
set -u

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$HERE/../.." && pwd)"
SUPCONF="$HERE/e2e_supervisord.conf"

if [ -n "${E2E_PYTHON:-}" ]; then
  PY="$E2E_PYTHON"
elif [ -x "${E2E_VENV_BIN:-$HOME/.venv/bin}/python3" ]; then
  PY="${E2E_VENV_BIN:-$HOME/.venv/bin}/python3"
else
  PY="python3"
fi
SUP_BIN="$(dirname "$PY")"   # supervisord/websockify live next to the interpreter

MSG="${E2E_MESSAGE:-}"
TIMEOUT="${E2E_TIMEOUT:-420}"
NEW_SESSION="${E2E_NEW_SESSION:-0}"
NO_SEND="${E2E_NO_SEND:-0}"

echo "== cleanup leftovers =="
"$SUP_BIN/supervisorctl" -c "$SUPCONF" shutdown >/dev/null 2>&1
pkill -f "supervisord -c $SUPCONF" >/dev/null 2>&1
pkill -f "uvicorn app.main:app" >/dev/null 2>&1
sleep 1

echo "== start supervisord (xvfb + chrome + websockify + sandbox :8080) =="
E2E_VENV_BIN="$SUP_BIN" "$SUP_BIN/supervisord" -c "$SUPCONF"
sleep 2

# wait until all sandbox services RUNNING
SANDBOX_OK=0
for i in $(seq 1 45); do
  ST=$(curl -s --max-time 3 http://localhost:8080/api/v1/supervisor/status 2>/dev/null)
  if echo "$ST" | python3 -c "
import sys, json
try:
    d = json.load(sys.stdin)
    procs = d.get('data') or []
    ok = bool(procs) and all(p.get('statename') == 'RUNNING' for p in procs)
    sys.exit(0 if ok else 1)
except Exception:
    sys.exit(1)
" 2>/dev/null; then
    SANDBOX_OK=1
    echo "sandbox services all RUNNING (after ${i}s)"
    break
  fi
  sleep 1
done
if [ "$SANDBOX_OK" != "1" ]; then
  echo "!! sandbox services NOT ready — status dump:"
  curl -s --max-time 3 http://localhost:8080/api/v1/supervisor/status | head -c 800; echo
  echo "-- /tmp/app_err.log tail:"; tail -20 /tmp/app_err.log 2>/dev/null
  echo "-- /tmp/chrome_err.log tail:"; tail -10 /tmp/chrome_err.log 2>/dev/null
fi

# CDP check — wait until chrome debugging endpoint is really answering
echo "== CDP check (chrome :8222) =="
CDP_OK=0
for i in $(seq 1 30); do
  if curl -s --max-time 3 http://localhost:8222/json/version 2>/dev/null | grep -q "Browser"; then
    CDP_OK=1
    echo "chrome CDP ready (after ${i}s)"
    break
  fi
  sleep 1
done
if [ "$CDP_OK" != "1" ]; then
  echo "!! chrome CDP NOT ready"
  tail -10 /tmp/chrome_err.log 2>/dev/null
fi

echo "== start backend (:8000) =="
cd "$REPO_ROOT/backend"
nohup "$PY" -m uvicorn app.main:app --host 0.0.0.0 --port 8000 > /tmp/backend_e2e.log 2>&1 &
BACKEND_PID=$!

BACKEND_OK=0
for i in $(seq 1 60); do
  H=$(curl -s --max-time 3 http://localhost:8000/health 2>/dev/null)
  if echo "$H" | grep -q '"ready":true'; then
    BACKEND_OK=1
    echo "backend ready (after ${i}s)"
    break
  fi
  sleep 1
done
if [ "$BACKEND_OK" != "1" ]; then
  echo "!! backend NOT ready — log tail:"
  tail -40 /tmp/backend_e2e.log
fi

echo "== run driver (timeout ${TIMEOUT}s) =="
DRIVER_ARGS=""
if [ "$NEW_SESSION" = "1" ]; then DRIVER_ARGS="$DRIVER_ARGS --new-session"; fi
if [ "$NO_SEND" = "1" ]; then DRIVER_ARGS="$DRIVER_ARGS --no-send"; fi
if [ -n "$MSG" ]; then
  E2E_MESSAGE="$MSG" E2E_TIMEOUT="$TIMEOUT" "$PY" "$HERE/e2e_driver.py" $DRIVER_ARGS --message "$MSG" --timeout "$TIMEOUT"
else
  E2E_TIMEOUT="$TIMEOUT" "$PY" "$HERE/e2e_driver.py" $DRIVER_ARGS --timeout "$TIMEOUT"
fi
DRIVER_EXIT=$?
echo "driver exit code: $DRIVER_EXIT"

echo "== cleanup =="
kill $BACKEND_PID >/dev/null 2>&1
sleep 1
"$SUP_BIN/supervisorctl" -c "$SUPCONF" shutdown >/dev/null 2>&1
pkill -f "uvicorn app.main:app" >/dev/null 2>&1
pkill -f "chrome-linux64/chrome" >/dev/null 2>&1
pkill -f Xvfb >/dev/null 2>&1
echo "backend log tail (last 25 lines):"
tail -25 /tmp/backend_e2e.log
exit $DRIVER_EXIT
