#!/data/data/com.termux/files/usr/bin/bash
# ═══════════════════════════════════════════════════════════════════════════
# Dzeck AI Agent — installer Termux (Android) sekali-jalan
#
#   bash install_termux.sh            # instal penuh (deps + build + mongo)
#   bash install_termux.sh --skip-fe  # lewati build frontend
#
# Jalankan SEKALI di Termux — semua dependensi (toolchain build, Python venv,
# paket backend, MongoDB via proot-distro, build frontend, backend/.env)
# dipasang otomatis. Setelah selesai: `bash start_termux.sh` untuk menjalankan.
#
# Ringkasan lingkungan Termux (kenapa skrip ini ada):
#   • Android aarch64 (Bionic libc) — wheel manylinux PyPI TIDAK terpasang;
#     paket berat diambil dari repo Termux (python-numpy, python-cryptography,
#     python-psutil, python-pillow, python-lxml) atau dibangun dari sumber.
#   • Tidak ada paket MongoDB di Termux → mongod resmi aarch64 dijalankan di
#     dalam proot-distro Ubuntu (satu perangkat, localhost:27017 sama).
#   • Tidak ada supervisord/systemd → sandbox API jalan standalone
#     (SANDBOX_STANDALONE=1) dan semua service di-start oleh start_termux.sh.
#   • Browser/VNC bersifat OPSIONAL (Xvfb/x11vnc dipasang bila tersedia);
#     tanpa Chrome, tool browser gagal per-panggilan secara mulai.
# ═══════════════════════════════════════════════════════════════════════════
set -uo pipefail

# ── Warna & util kecil ──────────────────────────────────────────────────────
if [ -t 1 ]; then
    B=$'\033[1m'; G=$'\033[32m'; Y=$'\033[33m'; R=$'\033[31m'; C=$'\033[36m'; N=$'\033[0m'
else
    B=""; G=""; Y=""; R=""; C=""; N=""
fi
step()  { printf "\n%s[==]%s %s%s%s\n" "$C" "$B" "$B" "$1" "$N"; }
ok()    { printf "%s[ok]%s %s\n" "$G" "$N" "$1"; }
warn()  { printf "%s[!]%s %s\n" "$Y" "$N" "$1"; }
die()   { printf "%s[gagal]%s %s\n" "$R" "$N" "$1" >&2; exit 1; }

# ── 0. Preflight: hanya Termux ─────────────────────────────────────────────
step "Preflight — verifikasi lingkungan Termux"
[ -n "${TERMUX_VERSION:-}" ] || [ "${PREFIX:-}" = "/data/data/com.termux/files/usr" ] || die \
    "Skrip ini KHUSUS Termux. Di desktop/Replit/E2B gunakan install_v2.sh.
    Termux: https://f-droid.org/packages/com.termux/  (bukan versi Play Store)"
command -v pkg >/dev/null 2>&1 || die "pkg tidak ditemukan — ini bukan Termux."
ok "Termux ${TERMUX_VERSION:-(?)} terdeteksi: $PREFIX"

# Repo root = direktori tempat skrip ini berada.
REPO="$(cd "$(dirname "$0")" && pwd)"
VENV="$REPO/.venv"
LOGDIR="$REPO/logs"
mkdir -p "$LOGDIR"
ok "Repo: $REPO"

SKIP_FE=0
[ "${1:-}" = "--skip-fe" ] && SKIP_FE=1

# Jangan biarkan layar mati di tengah build panjang.
command -v termux-wake-lock >/dev/null 2>&1 && termux-wake-lock 2>/dev/null && ok "wake-lock aktif"

# ── 1. Paket dasar Termux ──────────────────────────────────────────────────
step "1/8 — pkg update + paket dasar (toolchain build, runtime)"
yes | pkg update -y >/dev/null 2>&1 || warn "pkg update gagal (jaringan/mirror) — lanjut"
PKG_CORE="python python-pip git curl clang make cmake ninja binutils pkg-config \
libffi openssl rust nodejs redis proot-distro brotli libcurl \
python-numpy python-cryptography python-psutil python-pillow python-lxml"
ok "Memasang: $PKG_CORE (beberapa menit)"
pkg install -y $PKG_CORE || {
    warn "pkg install massal gagal — ulangi satu per satu (yang gagal dilewati)…"
    for p in $PKG_CORE; do
        pkg install -y "$p" >/dev/null 2>&1 || warn "  paket '$p' gagal — dilewati"
    done
}
# Verifikasi paket kritis. PENTING: cek nama BINARI, bukan nama PAKET —
# paket 'rust' menyediakan binari rustc/cargo (TIDAK ada binari 'rust'),
# paket 'nodejs' menyediakan binari 'node' (TIDAK ada binari 'nodejs').
# Cek nama paket membuat verifikasi selalu gagal walau paket sudah terpasang.
MISSING=""
for c in python git clang make cargo rustc proot-distro; do
    command -v "$c" >/dev/null 2>&1 || MISSING="$MISSING $c"
done
python -m pip --version >/dev/null 2>&1 || MISSING="$MISSING pip"
if [ -n "$MISSING" ]; then
    warn "Paket kritis kurang:$MISSING — coba sekali lagi (output penuh agar penyebabnya terlihat)…"
    for p in $MISSING; do
        # petakan nama binari → nama paket Termux
        case "$p" in
            pip)          PKG_NAME="python-pip" ;;
            cargo|rustc)  PKG_NAME="rust" ;;
            node)         PKG_NAME="nodejs" ;;
            *)            PKG_NAME="$p" ;;
        esac
        pkg install -y "$PKG_NAME" || warn "  paket '$PKG_NAME' tetap gagal — lihat pesan apt di atas"
    done
    # Re-verify setelah percobaan kedua.
    MISSING=""
    for c in python git clang make cargo rustc proot-distro; do
        command -v "$c" >/dev/null 2>&1 || MISSING="$MISSING $c"
    done
    python -m pip --version >/dev/null 2>&1 || MISSING="$MISSING pip"
fi
[ -z "$MISSING" ] || die "paket kritis belum terpasang:$MISSING
    Penyebab umum: (1) storage penuh  — cek: df -h \$PREFIX  (butuh ±3GB bebas)
    (2) mirror tak sinkron — termux-change-repo → pilih Mirror Group
    (3) dpkg terputus — jalankan: dpkg --configure -a  lalu ulangi skrip."
# nodejs: SOFT requirement — tanpa node, build frontend dilewati (backend tetap jalan).
if ! command -v node >/dev/null 2>&1; then
    warn "nodejs tidak terpasang — build frontend akan DILEWATI (backend tetap jalan)."
    SKIP_FE=1
fi
ok "Paket inti + paket Python prebuilt Termux terpasang"

step "1b — paket opsional (best-effort, boleh gagal)"
# x11-repo: Xvfb/x11vnc untuk browser+VNC opsional; tur-repo: repo komunitas
# (sumber python-pandas prebuilt bila tersedia utk varian Android ini).
pkg install -y x11-repo >/dev/null 2>&1 && pkg install -y xvfb x11vnc >/dev/null 2>&1 \
    && ok "Xvfb + x11vnc terpasang (browser/VNC opsional tersedia)" \
    || warn "Xvfb/x11vnc tidak terpasang — browser/live-view dinonaktifkan (dokumentasi: TERMUX.md)"
pkg install -y tur-repo >/dev/null 2>&1 || true

# ── 2. Virtualenv Python (system-site-packages → pakai numpy Termux) ──────
step "2/8 — virtualenv Python ($VENV)"
if [ ! -x "$VENV/bin/python" ]; then
    python -m venv --system-site-packages "$VENV" || die "pembuatan venv gagal"
fi
# shellcheck disable=SC1091
source "$VENV/bin/activate"
pip install -q --upgrade pip setuptools wheel || warn "upgrade pip gagal — lanjut"
# Build-backend murni-Python untuk build dari sumber tanpa isolasi.
# CATATAN: 'ninja' PyPI sengaja TIDAK dipasang — wheel-nya manylinux (tak valid
# di Termux) dan binary ninja dari pkg sudah tersedia di PATH (tahap 1).
pip install -q cython meson meson-python versioningit scikit-build-core cffi \
    || warn "beberapa build-backend gagal dipasang"
ok "venv siap: python $(python -V 2>&1 | awk '{print $2}')"

# ── 3. Rantai pydantic (pydantic-core: build Rust via maturin) ────────────
step "3/8 — pydantic + pydantic-core (build Rust — 5-15 menit)"
if python -c "import pydantic, pydantic_core" >/dev/null 2>&1; then
    ok "pydantic sudah ada — lewati"
else
    # maturin: coba biner resmi repo Termux dulu (detik), fallback cargo (menit).
    if ! command -v maturin >/dev/null 2>&1; then
        ok "mencoba pkg install maturin (biner resmi Termux)…"
        pkg install -y maturin >/dev/null 2>&1 || true
    fi
    if ! command -v maturin >/dev/null 2>&1; then
        export PATH="$HOME/.cargo/bin:$PATH"
        ok "maturin belum ada → cargo install maturin (sekali saja, sabar…)"
        cargo install maturin --locked || die "cargo install maturin gagal — cek log Rust di atas."
    fi
    ok "maturin $(maturin --version 2>/dev/null | awk '{print $2}') siap"
    # Pasang pydantic TANPA deps (wheel pydantic-core di PyPI manylinux — tak
    # valid di Termux), TERMASUK deps murni yang wajib ada:
    pip install -q --no-deps pydantic pydantic-settings typing-inspection \
        annotated-types typing-extensions \
        || die "pip install pydantic gagal"
    # Versi pydantic-core yang dibutuhkan dibaca dari metadata pydantic.
    # FIX BUG: pydantic versi baru menulis nama dep sebagai "pydantic_core"
    # (underscore) dan/atau format "(==x.y.z)" berkurung + env marker —
    # parser lama (startswith 'pydantic-core==') jadi tidak cocok → versi
    # kosong → 'pip install pydantic-core==' error. Normalisasi dulu:
    CORE_VER="$(python -c '
from importlib.metadata import requires
for r in (requires("pydantic") or []):
    spec = r.split(";")[0].strip()                 # buang env marker
    spec = spec.replace("(", " ").replace(")", " ")  # buang kurung
    name = spec.replace("_", "-").lower().split("==")[0].strip()
    if name == "pydantic-core" and "==" in spec:
        print(spec.split("==", 1)[1].strip())
        break
' 2>/dev/null || true)"
    if [ -n "$CORE_VER" ]; then
        ok "Membangun pydantic-core $CORE_VER dari sumber…"
        pip install --no-build-isolation "pydantic-core==$CORE_VER" \
            || die "build pydantic-core gagal (butuh RAM ~2GB; tutup aplikasi lain dan ulangi)."
    else
        # Fallback aman: pydantic terbaru selalu seiring dengan pydantic-core
        # terbaru (rilis lockstep) — pasang tanpa pin.
        warn "Versi pydantic-core tidak terbaca dari metadata — pasang pydantic-core terbaru (padanan lockstep)."
        pip install --no-build-isolation --no-deps pydantic-core \
            || die "build pydantic-core gagal (butuh RAM ~2GB; tutup aplikasi lain dan ulangi)."
    fi
fi
python -c "import pydantic, pydantic_core" >/dev/null 2>&1 \
    && ok "pydantic OK ($(python -c 'import pydantic;print(pydantic.VERSION)' 2>/dev/null))" \
    || die "pydantic/pydantic-core masih gagal diimpor — jalankan ulang install_termux.sh."

# ── 4. Paket berat: pandas & curl-cffi (boleh gagal → degradasi) ──────────
step "4/8 — pandas & curl-cffi (build berat; gagal = degradasi fungsional)"
HEAVY_FAILED=0

if python -c "import pandas" >/dev/null 2>&1; then
    ok "pandas sudah ada — lewati"
else
    # Coba repo prebuilt (TUR) dulu, lalu build sumber (lama: 20-45 menit di HP).
    if pkg install -y python-pandas >/dev/null 2>&1 && "$VENV/bin/python" -c "import pandas" >/dev/null 2>&1; then
        ok "pandas terpasang dari repo Termux/TUR"
    else
        warn "Membangun pandas 2.2.3 dari sumber — 20-45 menit di HP. Aktifkan pengisi daya."
        if pip install --no-build-isolation "pandas==2.2.3" 2>"$LOGDIR/pandas_build.log"; then
            ok "pandas selesai dibangun"
        else
            warn "pandas GAGAL dibangun (log: $LOGDIR/pandas_build.log) — lanjut tanpa pandas (analisa .xlsx via openpyxl masih jalan)."
            HEAVY_FAILED=1
        fi
    fi
fi

if python -c "import curl_cffi" >/dev/null 2>&1; then
    ok "curl_cffi sudah ada — lewati"
else
    warn "Membangun curl-cffi dari sumber (cmake)…"
    if pip install --no-build-isolation curl-cffi 2>"$LOGDIR/curl_cffi_build.log"; then
        ok "curl-cffi selesai dibangun"
    else
        warn "curl-cffi GAGAL (log: $LOGDIR/curl_cffi_build.log) — search scraping otomatis degradasi ke provider API (kode sudah siap)."
        HEAVY_FAILED=1
    fi
fi

# ── 5. Dependensi backend lengkap ─────────────────────────────────────────
step "5/8 — dependensi backend (pip install -e backend)"
if [ "$HEAVY_FAILED" = 0 ]; then
    pip install -e "$REPO/backend" || die "pip install backend gagal — jalankan ulang skrip untuk mencoba lagi."
else
    # Degradasi: pasang backend tanpa deps + daftar dependensi murni-Python
    # secara eksplisit (pandas/curl-cffi yang gagal tidak menggagalkan semua).
    warn "Memakai jalur degradasi: backend tanpa pandas/curl-cffi"
    pip install --no-deps -e "$REPO/backend" || die "pip install --no-deps backend gagal"
    pip install -q beanie cryptography debugpy fastapi httpx "pyjwt[crypto]" pymongo \
        python-dotenv python-multipart redis sse-starlette uvicorn websockets \
        langchain langchain-classic langchain-openai openai browser-use e2b playwright \
        psutil tavily-python beautifulsoup4 markdownify mcp openpyxl pdfplumber \
        python-docx python-pptx || warn "sebagian dependensi murni gagal — periksa log pip"
fi
python -c "import fastapi, uvicorn, beanie" && ok "backend dependencies OK"

# Deps pengujian (opsional tapi berguna untuk verifikasi 100% Passed di HP).
pip install -q pytest pytest-asyncio pytest-mock requests || true

# ── 6. MongoDB resmi aarch64 di dalam proot-distro Ubuntu ─────────────────
step "6/8 — MongoDB (proot-distro Ubuntu, localhost:27017)"
MONGO_TARBALL="https://fastdl.mongodb.org/linux/mongodb-linux-aarch64-ubuntu2204-8.0.4.tgz"
if command -v mongod >/dev/null 2>&1; then
    ok "mongod sudah tersedia di PATH — lewati"
else
    # Deteksi rootfs langsung dari direktori — output `proot-distro list`
    # peka spasi/baris sehingga grep "ubuntu.*: installed" sering false-negative
    # (memicu reinstall ulang yang gagal pada run kedua).
    if ! ls -d "$PREFIX"/var/lib/proot-distro/installed-rootfs/ubuntu* >/dev/null 2>&1; then
        ok "proot-distro install ubuntu (rootfs ~30MB)…"
        proot-distro install ubuntu || die "proot-distro install ubuntu gagal"
    fi
    ROOTFS="$(ls -d "$PREFIX"/var/lib/proot-distro/installed-rootfs/ubuntu* 2>/dev/null | head -1)"
    [ -n "$ROOTFS" ] || die "rootfs ubuntu tidak ditemukan setelah instalasi proot-distro"
    if [ ! -x "$ROOTFS/opt/mongodb/bin/mongod" ]; then
        ok "Mengunduh MongoDB 8.0.4 aarch64 (resmi, ~90MB)…"
        curl -fL --retry 3 -o "$LOGDIR/mongodb.tgz" "$MONGO_TARBALL" \
            || die "unduhan MongoDB gagal — periksa koneksi lalu jalankan ulang."
        mkdir -p "$ROOTFS/opt/mongodb" "$ROOTFS/data/db" "$ROOTFS/var/log/mongodb"
        tar -xzf "$LOGDIR/mongodb.tgz" -C "$ROOTFS/opt/mongodb" --strip-components=1 \
            || die "ekstraksi MongoDB gagal"
        rm -f "$LOGDIR/mongodb.tgz"
        ok "mongod terpasang di rootfs:/opt/mongodb/bin/mongod"
    fi
fi
# Helper start/stop/status dipakai installer & start_termux.sh.
chmod +x "$REPO/scripts/termux_mongo.sh" 2>/dev/null || true
bash "$REPO/scripts/termux_mongo.sh" start || warn "mongod belum bisa di-start sekarang — jalankan: bash scripts/termux_mongo.sh start"
ok "MongoDB siap (mongodb://localhost:27017)"

# ── 7. Frontend (build produksi → backend menyajikan dist) ────────────────
step "7/8 — frontend (npm install + vite build)"
if [ "$SKIP_FE" = 1 ]; then
    warn "dilewati (--skip-fe)"
elif [ -f "$REPO/frontend/dist/index.html" ]; then
    ok "frontend/dist sudah ada — lewati (hapus folder dist untuk rebuild)"
else
    ( cd "$REPO/frontend" && npm install --no-audit --no-fund 2>"$LOGDIR/npm_install.log" ) \
        || die "npm install gagal (log: $LOGDIR/npm_install.log)"
    if ( cd "$REPO/frontend" && npm run build 2>"$LOGDIR/npm_build.log" ); then
        ok "frontend build OK → frontend/dist (disajikan oleh backend di :8000)"
    else
        warn "vite build gagal (log: $LOGDIR/npm_build.log) — UI bisa dibangun ulang nanti: cd frontend && npm run build"
    fi
fi

# ── 8. backend/.env dengan default Termux ─────────────────────────────────
step "8/8 — backend/.env (default Termux)"
ENV_FILE="$REPO/backend/.env"
if [ -f "$ENV_FILE" ]; then
    ok "backend/.env sudah ada — tidak diubah (milikmu)."
else
    USER_ROOT="$HOME/dzeck/users"
    cat > "$ENV_FILE" <<EOF
# Dibuat otomatis oleh install_termux.sh — sesuaikan API_KEY milikmu!
AGENT_PROVIDER=existing
API_KEY=
API_BASE=https://integrate.api.nvidia.com/v1
MODEL_NAME=nvidia/nemotron-3-super-120b-a12b
MODEL_PROVIDER=openai
TEMPERATURE=0.7
MAX_TOKENS=8000

SANDBOX_PROVIDER=local
USER_HOME_ROOT=$USER_ROOT
SANDBOX_PROTECTED_PATHS=$REPO
MCP_CONFIG_PATH=$REPO/backend/mcp.json

MONGODB_URI=mongodb://localhost:27017
MONGODB_DATABASE=dzeck
REDIS_HOST=localhost
REDIS_PORT=6379
EOF
    warn "backend/.env dibuat — ISI API_KEY (NVIDIA NIM) sebelum start!"
    ok "  nano $ENV_FILE"
fi

# ── Ringkasan ──────────────────────────────────────────────────────────────
printf "\n%s%s═══ INSTALASI TERMUX SELESAI ═══%s\n" "$B" "$G" "$N"
ok  "Mulai semua service : bash start_termux.sh"
ok  "Aplikasi            : http://localhost:8000"
ok  "MongoDB             : bash scripts/termux_mongo.sh {start|stop|status}"
[ "$HEAVY_FAILED" = 0 ] || warn "Ada paket berat yang gagal (lihat peringatan di atas) — fitur terkait terdegradasi otomatis, sisanya jalan normal."
warn "Lepas wake-lock kapan saja: termux-wake-unlock"
printf "\n"
