#!/bin/bash

# Start Xvfb
rm -f /tmp/.X1-lock
Xvfb :1 -screen 0 1280x1029x24 &
export DISPLAY=:1

# Wait for Xvfb to be ready
sleep 2

# Start Chromium
chromium \
    --display=:1 \
    --window-size=1280,1029 \
    --start-maximized \
    --no-sandbox \
    --disable-dev-shm-usage \
    --disable-setuid-sandbox \
    --disable-accelerated-2d-canvas \
    --disable-gpu \
    --disable-features=WelcomeExperience,SigninPromo \
    --no-first-run \
    --no-default-browser-check \
    --disable-infobars \
    --test-type \
    --disable-popup-blocking \
    --disable-gpu-sandbox \
    --no-xshm \
    --new-window=false \
    --disable-notifications \
    --disable-extensions \
    --disable-component-extensions-with-background-pages \
    --disable-popup-blocking \
    --disable-prompt-on-repost \
    --disable-dialogs \
    --disable-modal-dialogs \
    --disable-web-security \
    --disable-site-isolation-trials \
    --remote-debugging-address=0.0.0.0 \
    --remote-debugging-port=8222 $CHROME_ARGS &

# Start socat for port forwarding
socat TCP-LISTEN:9222,bind=0.0.0.0,fork,reuseaddr TCP:127.0.0.1:8222 &

# Start x11vnc
x11vnc -display :1 -nopw -shared -listen 0.0.0.0 -xkb -forever -rfbport 5900 &

# Start websockify
websockify 0.0.0.0:5901 localhost:5900 &

# Start FastAPI application
cd /app
uv run uvicorn app.main:app --host 0.0.0.0 --port 8080 $UVI_ARGS

# Keep script running if uvicorn exits (optional, for debugging)
# wait
