#!/bin/bash
set -e

echo "=== Post-merge setup ==="

echo "--- Installing backend Python dependencies ---"
cd backend
pip install -e . --quiet
cd ..

echo "--- Installing sandbox system dependencies ---"
pip install supervisor websockify --quiet

echo "--- Installing frontend Node dependencies ---"
cd frontend
pnpm install --frozen-lockfile 2>/dev/null || pnpm install
cd ..

echo "=== Post-merge setup complete ==="
