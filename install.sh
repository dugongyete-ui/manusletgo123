#!/usr/bin/env bash
set -e

echo "========================================"
echo "  AI Dzeck — Install Script"
echo "========================================"

# ── 0. Prerequisites check ────────────────────────────────────────────────────
echo ""
echo "[0/5] Checking prerequisites..."

if ! command -v python3 &>/dev/null; then
  echo "ERROR: python3 not found. Install Python 3.12 or later." && exit 1
fi
PY_VER=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
PY_MAJOR=$(python3 -c "import sys; print(sys.version_info.major)")
PY_MINOR=$(python3 -c "import sys; print(sys.version_info.minor)")
if [ "$PY_MAJOR" -lt 3 ] || { [ "$PY_MAJOR" -eq 3 ] && [ "$PY_MINOR" -lt 12 ]; }; then
  echo "ERROR: Python 3.12+ required, found $PY_VER" && exit 1
fi
echo "      Python $PY_VER OK"

if ! command -v node &>/dev/null; then
  echo "ERROR: node not found. Install Node.js 18 or later." && exit 1
fi
NODE_VER=$(node --version)
echo "      Node.js $NODE_VER OK"

if ! command -v pnpm &>/dev/null; then
  echo "      pnpm not found — installing via npm..."
  npm install -g pnpm
fi
PNPM_VER=$(pnpm --version)
echo "      pnpm $PNPM_VER OK"

# ── Detect pip install flags ──────────────────────────────────────────────────
PIP_FLAGS=""
if python3 -m pip install --break-system-packages --dry-run pip &>/dev/null 2>&1; then
  PIP_FLAGS="--break-system-packages"
fi

# Upgrade pip/setuptools first to avoid resolver issues
python3 -m pip install $PIP_FLAGS -q --upgrade pip setuptools wheel 2>/dev/null || true

# ── 1. Frontend dependencies ──────────────────────────────────────────────────
echo ""
echo "[1/5] Installing frontend dependencies..."
cd frontend
pnpm approve-builds --yes 2>/dev/null || true
pnpm install --frozen-lockfile 2>/dev/null || pnpm install
cd ..
echo "      Frontend dependencies installed"

# ── 2. Core backend dependencies ─────────────────────────────────────────────
echo ""
echo "[2/5] Installing core backend dependencies..."

python3 -m pip install $PIP_FLAGS -q \
  "fastapi>=0.121.2" \
  "uvicorn>=0.38.0" \
  "beanie>=1.25.0" \
  "redis>=5.0.1" \
  "pydantic>=2.12.4" \
  "pydantic-settings>=2.12.0" \
  "email-validator>=2.3.0" \
  "python-dotenv>=1.2.1" \
  "python-multipart>=0.0.20" \
  "pyjwt[crypto]>=2.8.0" \
  "pymongo>=4.14.0" \
  "sse-starlette>=3.0.3" \
  "websockets>=15.0.1" \
  "httpx>=0.28.1" \
  "cryptography>=3.4.8"

echo "      Core dependencies installed"

# ── 3. AI / LLM dependencies ─────────────────────────────────────────────────
#
#  Install order matters to avoid version conflicts:
#  1. Pin openai to a range accepted by BOTH langchain and browser-use
#  2. Install langchain stack (openai provider only)
#  3. Install browser-use (will pull compatible openai transitively)
#
echo ""
echo "[3/5] Installing AI/LLM dependencies..."

# 3a. LangChain ecosystem — openai provider only
python3 -m pip install $PIP_FLAGS -q \
  "openai>=2.8.0" \
  "langchain>=1.0.7" \
  "langchain-classic>=1.0.7" \
  "langchain-openai>=1.0.3"

# 3b. browser-use + Playwright (cdp-use, bubus, rich are transitive deps — installed automatically)
python3 -m pip install $PIP_FLAGS -q "browser-use>=0.12.1"
python3 -m pip install $PIP_FLAGS -q "playwright>=1.42.0"
python3 -m pip install $PIP_FLAGS -q "patchright>=1.42.0" 2>/dev/null || true

echo "      AI/LLM dependencies installed"

# ── 4. Utility dependencies ───────────────────────────────────────────────────
echo ""
echo "[4/5] Installing utility dependencies..."

python3 -m pip install $PIP_FLAGS -q \
  "curl-cffi>=0.14.0" \
  "beautifulsoup4>=4.12.0" \
  "markdownify>=1.2.0" \
  "tavily-python>=0.5.0" \
  "mcp>=1.9.0" \
  "psutil>=5.9.0" \
  "debugpy>=1.8.17" \
  "supervisor>=4.2.0" \
  "websockify>=0.11.0"

# ── 4b. File extraction dependencies ─────────────────────────────────────────
echo "      Installing file-extraction dependencies..."
python3 -m pip install $PIP_FLAGS -q \
  "python-docx>=1.2.0" \
  "python-pptx>=1.0.0" \
  "pdfplumber>=0.11.0" \
  "pandas>=2.0.0" \
  "openpyxl>=3.1.0"

echo "      Utility dependencies installed"

# ── 4c. Dev / test dependencies ───────────────────────────────────────────────
echo "      Installing dev/test dependencies..."
python3 -m pip install $PIP_FLAGS -q \
  "pytest>=7.0.0" \
  "pytest-asyncio>=0.21.0" \
  "pytest-cov>=4.0.0" \
  "pytest-mock>=3.10.0" \
  "requests>=2.28.0"

# ── Playwright browser binary ─────────────────────────────────────────────────
echo ""
echo "      Installing Playwright Chromium browser binary..."
python3 -m playwright install chromium 2>/dev/null || \
  python3 -m playwright install chromium --with-deps 2>/dev/null || \
  echo "      WARNING: Playwright browser install failed — sandbox browser will be used"

# ── 5. Environment configuration ─────────────────────────────────────────────
echo ""
echo "[5/5] Checking environment configuration..."

ENV_SRC=""
if [ -f .env.example ]; then
  ENV_SRC=".env.example"
elif [ -f backend/.env.example ]; then
  ENV_SRC="backend/.env.example"
fi

if [ ! -f backend/.env ]; then
  if [ -n "$ENV_SRC" ]; then
    cp "$ENV_SRC" backend/.env
    echo "      Created backend/.env from $ENV_SRC"
    echo "      Edit backend/.env and fill in your API keys before starting"
  else
    echo "      WARNING: No .env.example found — create backend/.env with your config"
    echo "      Required keys: MONGODB_URI, REDIS_HOST, REDIS_PORT, API_KEY, API_BASE"
    echo "      Optional:  TAVILY_API_KEY, VISION_MODEL_NAME"
  fi
else
  echo "      backend/.env already exists"
fi

# ── Done ──────────────────────────────────────────────────────────────────────
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
