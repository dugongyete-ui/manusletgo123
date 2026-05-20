#!/usr/bin/env bash
set -e

echo "========================================"
echo "  AI Manus x E2B — Install Script"
echo "========================================"

# ── 1. Frontend dependencies ─────────────────
echo ""
echo "[1/3] Installing frontend dependencies..."
cd frontend
pnpm install
cd ..
echo "      Frontend dependencies installed"

# ── 2. Backend Python dependencies ───────────
echo ""
echo "[2/3] Installing backend Python dependencies..."

python3 -m pip install \
  "fastapi>=0.121.2" \
  "uvicorn>=0.38.0" \
  "beanie>=1.25.0" \
  "redis>=5.0.1" \
  "pydantic>=2.12.4" \
  "pydantic-settings>=2.12.0" \
  "python-dotenv>=1.2.1" \
  "python-multipart>=0.0.20" \
  --break-system-packages -q

python3 -m pip install \
  "langchain>=1.0.7" \
  "langchain-openai>=1.0.3" \
  "langchain-anthropic>=1.2.0" \
  "langchain-deepseek>=1.0.1" \
  "langchain-ollama>=1.0.0" \
  "langchain-community>=0.4.1" \
  --break-system-packages -q

python3 -m pip install \
  "httpx>=0.28.1" \
  "pyjwt[crypto]>=2.8.0" \
  "pymongo>=4.14.0" \
  "sse-starlette>=3.0.3" \
  "websockets>=15.0.1" \
  "openai>=2.8.0" \
  "cryptography>=3.4.8" \
  "async-lru>=2.0.0" \
  --break-system-packages -q

python3 -m pip install \
  "e2b>=1.0.0" \
  "browser-use>=0.12.1" \
  "playwright>=1.42.0" \
  --break-system-packages -q

python3 -m pip install \
  "curl-cffi>=0.14.0" \
  "beautifulsoup4>=4.12.0" \
  "markdownify>=1.2.0" \
  "tavily-python>=0.5.0" \
  "mcp>=1.9.0" \
  "rich>=14.2.0" \
  "debugpy>=1.8.17" \
  --break-system-packages -q

echo "      Backend Python dependencies installed"

# ── 3. Environment configuration ─────────────
echo ""
echo "[3/3] Checking environment configuration..."
if [ ! -f backend/.env ]; then
  if [ -f .env.example ]; then
    cp .env.example backend/.env
    echo "      Created backend/.env from .env.example"
    echo "      Edit backend/.env and fill in your API keys before starting"
  else
    echo "      WARNING: No .env found — create backend/.env with your config"
  fi
else
  echo "      backend/.env already exists"
fi

echo ""
echo "========================================"
echo "  Installation complete!"
echo ""
echo "  Start the backend:"
echo "    cd backend && python3 -m uvicorn app.main:app --host localhost --port 8000"
echo ""
echo "  Start the frontend:"
echo "    cd frontend && pnpm dev"
echo "========================================"
