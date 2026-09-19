#!/usr/bin/env bash
# ============================================================================
#  AI Dzeck — install_v2.sh (z.ai sandbox edition)
#  Satu perintah: SEMUA dependencies terpasang + frontend ter-build + health.
#
#  Kenapa v2? install.sh dirancang untuk Replit (pnpm global, pip system,
#  registry npmjs penuh). Di sandbox z.ai:
#    - Python 3.12 sudah ada di venv /home/z/.venv (pakai uv bila tersedia)
#    - pnpm TIDAK ada, tapi bun & npm ada
#    - registry npmjs kadang memblokir sebagian tarball → perlu fallback
#      registry mirror (npmmirror) + fallback npm per-paket
#    - backend disajikan dari repo root: backend/app.main:app di port 8000
#
#  Pemakaian:  bash install_v2.sh            (install + build + health check)
#              bash install_v2.sh --start    (…lalu jalankan server background)
#  Idempotent: aman dijalankan berulang kali.
# ============================================================================
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND="$ROOT/backend"
FRONTEND="$ROOT/frontend"
START_SERVER=0
[ "${1:-}" = "--start" ] && START_SERVER=1

log()  { printf '\033[1;34m[install_v2]\033[0m %s\n' "$*"; }
ok()   { printf '\033[1;32m[OK]\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m[WARN]\033[0m %s\n' "$*"; }
die()  { printf '\033[1;31m[ERROR]\033[0m %s\n' "$*"; exit 1; }

echo "========================================"
echo "  AI Dzeck — install_v2 (z.ai edition)"
echo "========================================"

# ── [0/6] Prasyarat ─────────────────────────────────────────────────────────
log "[0/6] Cek prasyarat…"

command -v python3 >/dev/null 2>&1 || die "python3 tidak ditemukan"
PY_VER=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
python3 -c "import sys; exit(0 if sys.version_info >= (3,12) else 1)" \
  || die "Python 3.12+ dibutuhkan, ditemukan $PY_VER"
ok "Python $PY_VER"

PY_PKG="python3 -m pip"
if command -v uv >/dev/null 2>&1; then
  PY_PKG="uv pip"
  ok "uv tersedia (install Python paket lebih cepat)"
else
  ok "pip tersedia"
fi

command -v node >/dev/null 2>&1 || die "node tidak ditemukan (Node 18+)"
ok "Node.js $(node --version)"

USE_BUN=0
if command -v bun >/dev/null 2>&1; then USE_BUN=1; ok "bun $(bun --version)"; fi
command -v npm >/dev/null 2>&1 || die "npm tidak ditemukan"

# ── [1/6] Dependensi backend (Python) ──────────────────────────────────────
log "[1/6] Pasang dependensi backend (pyproject.toml)…"
if $PY_PKG install -r "$BACKEND/pyproject.toml" --quiet 2>/dev/null; then
  ok "Dependensi backend terpasang (dari pyproject.toml)"
else
  warn "Instal dari pyproject gagal — fallback ke daftar paket inti…"
  $PY_PKG install --quiet \
    "fastapi>=0.121.2" "uvicorn>=0.38.0" "beanie>=1.25.0" "redis>=5.0.1" \
    "pydantic>=2.12.4" "pydantic-settings>=2.12.0" "python-dotenv>=1.2.1" \
    "python-multipart>=0.0.20" "pyjwt[crypto]>=2.8.0" "pymongo>=4.14.0" \
    "sse-starlette>=3.0.3" "websockets>=15.0.1" "httpx>=0.28.1" \
    "cryptography>=3.4.8" "openai>=2.8.0" "langchain-openai>=1.0.3" \
    "psutil>=5.9.0" "tavily-python>=0.5.0" "beautifulsoup4>=4.12.0" \
    "markdownify" "mcp>=1.9.0" "openpyxl>=3.1.0" "pandas>=2.0.0" \
    "pdfplumber>=0.11.0" "python-docx>=1.2.0" "python-pptx>=1.0.0" \
    "playwright>=1.42.0" "e2b>=2.0.0" || die "Instal dependensi backend gagal"
  ok "Dependensi inti backend terpasang"
fi

# Verifikasi impor kritis (cepat, tanpa menjalankan server)
python3 - <<'PYEOF' || die "Verifikasi impor backend gagal — cek pesan di atas"
import importlib
mods = ["fastapi", "uvicorn", "beanie", "redis", "pydantic_settings", "jwt",
        "pymongo", "sse_starlette", "httpx", "openai", "e2b"]
missing = []
for m in mods:
    try:
        importlib.import_module(m)
    except Exception as e:
        missing.append(f"{m} ({e.__class__.__name__})")
if missing:
    print("MODUL GAGAL:", ", ".join(missing)); raise SystemExit(1)
import e2b
from e2b import AsyncSandbox  # gaya API e2b v2 — wajib e2b>=2.0.0
print("Semua modul backend OK — e2b AsyncSandbox (v2 style) importable")
PYEOF
ok "e2b SDK sinkron (v2 AsyncSandbox) — fallback E2B→Replit siap"

# ── [2/6] Dependensi frontend ──────────────────────────────────────────────
log "[2/6] Pasang dependensi frontend…"
cd "$FRONTEND"

install_frontend_pkgs() {
  # $1 = package manager command prefix
  if [ "$USE_BUN" = "1" ]; then
    bun install 2>&1 && return 0
    warn "bun gagal sebagian — coba registry mirror npmmirror…"
    bun install --registry https://registry.npmmirror.com 2>&1 && return 0
  fi
  npm install --no-audit --no-fund 2>&1 && return 0
  warn "npm bawaan gagal — coba registry mirror…"
  npm install --no-audit --no-fund --registry=https://registry.npmmirror.com 2>&1
}
install_frontend_pkgs || die "Instal dependensi frontend gagal"

# Paket yang sering diblok registry — pastikan ada (fallback npm satu-per-satu)
for PKG in "highlight.js@11.11.1" "marked-highlight@2.2.4" "typescript@5.4.5"; do
  NAME="${PKG%%@*}"
  if [ ! -d "node_modules/$NAME" ]; then
    warn "$NAME hilang — pasang manual via npm…"
    npm install "$PKG" --no-audit --no-fund --no-save || \
      npm install "$PKG" --no-audit --no-fund --no-save --registry=https://registry.npmmirror.com \
      || die "Gagal memasang $NAME"
  fi
done
ok "Dependensi frontend terpasang"

# ── [3/6] Build frontend (vite → dist/) ────────────────────────────────────
log "[3/6] Build frontend (vite)…"
VITE="$FRONTEND/node_modules/.bin/vite"
if [ -x "$VITE" ]; then
  (cd "$FRONTEND" && "$VITE" build) || die "vite build gagal"
else
  (cd "$FRONTEND" && npm run build) || die "npm run build gagal"
fi
[ -f "$FRONTEND/dist/index.html" ] || die "dist/index.html tidak ada setelah build"
ok "Frontend ter-build → frontend/dist/"

# ── [4/6] Browser engine (opsional, non-fatal) ─────────────────────────────
log "[4/6] Chromium untuk playwright (opsional)…"
if python3 -m playwright install chromium >/dev/null 2>&1; then
  ok "Chromium playwright terpasang"
else
  warn "Chromium gagal dipasang — browser tools tetap bisa jalan via engine lain (non-fatal)"
fi

# ── [5/6] Konfigurasi (.env) ────────────────────────────────────────────────
log "[5/6] Cek konfigurasi…"
if [ -f "$BACKEND/.env" ]; then
  ok "backend/.env ditemukan"
  grep -q '^SANDBOX_PROVIDER=' "$BACKEND/.env" || {
    echo 'SANDBOX_PROVIDER=auto' >> "$BACKEND/.env"
    warn "SANDBOX_PROVIDER belum ada — ditambahkan sebagai 'auto'"
  }
else
  warn "backend/.env TIDAK ada! Salin dari template lalu isi kredensial:"
  warn "  cp backend/.env.example backend/.env   (atau minta konfigurasi ke admin)"
fi

# ── [6/6] Ringkasan + opsi start ────────────────────────────────────────────
log "[6/6] Selesai. Ringkasan:"
echo "  ├─ Backend  : FastAPI  → uvicorn app.main:app  (port 8000)"
echo "  ├─ Frontend : dist/ Vue 3 (disajikan backend, SPA fallback)"
echo "  ├─ Sandbox  : SANDBOX_PROVIDER=auto → E2B dulu, kuota habis → Replit"
echo "  └─ Jalankan : bash backend/run_backend.sh   (atau: bash install_v2.sh --start)"

if [ "$START_SERVER" = "1" ]; then
  log "Menjalankan server di background (log: backend/server.log)…"
  cd "$BACKEND"
  set -a; # shellcheck disable=SC1091
  [ -f .env ] && source .env; set +a
  nohup python3 -m uvicorn app.main:app --host 0.0.0.0 --port 8000 \
    >> "$BACKEND/server.log" 2>&1 &
  echo $! > "$BACKEND/server.pid"
  sleep 8
  if curl -sf http://localhost:8000/health >/dev/null 2>&1; then
    ok "Server HIDUP: http://localhost:8000  (PID $(cat "$BACKEND/server.pid"))"
  else
    warn "Server belum merespons — periksa: tail -50 $BACKEND/server.log"
  fi
fi

echo ""
ok "install_v2 selesai."
