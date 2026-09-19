#!/data/data/com.termux/files/usr/bin/bash
# ═══════════════════════════════════════════════════════════════════════════
# Dzeck AI Agent — start semua service di Termux (Android)
#
#   bash start_termux.sh          # mongo + redis + sandbox API + backend
#   bash start_termux.sh stop     # hentikan semua
#   bash start_termux.sh status   # cek port 27017/6379/8080/8000
#
# Urutan: MongoDB (proot) → Redis → sandbox API (8080, standalone) →
# backend (8000, sekaligus menyajikan frontend/dist bila ada).
# Log per service: logs/*.log di folder repo.
# ═══════════════════════════════════════════════════════════════════════════
set -uo pipefail

if [ -n "${TERMUX_VERSION:-}" ] || [ "${PREFIX:-}" = "/data/data/com.termux/files/usr" ]; then
    :  # Termux OK
else
    echo "[!] start_termux.sh khusus Termux." >&2; exit 1
fi

REPO="$(cd "$(dirname "$0")" && pwd)"
LOGDIR="$REPO/logs"; mkdir -p "$LOGDIR"
command -v termux-wake-lock >/dev/null 2>&1 && termux-wake-lock 2>/dev/null
# Python interpreter: venv hasil install_termux.sh bila ada, else python3.
if [ -x "$REPO/.venv/bin/python" ]; then PY="$REPO/.venv/bin/python"; else PY="python3"; fi

port_up() { (echo >/dev/tcp/127.0.0.1/"$1") >/dev/null 2>&1; }   # bash TCP probe

wait_port() { # wait_port <port> <nama> <maks-detik>
    local i=0
    while [ "$i" -lt "$3" ]; do
        port_up "$1" && return 0
        sleep 1; i=$((i + 1))
    done
    echo "[!] $2 belum mendengarkan di :$1 setelah ${3}s (log: $LOGDIR)" >&2
    return 1
}

do_stop() {
    echo "[==] Menghentikan service Dzeck…"
    pkill -f "uvicorn app.main:app --host 0.0.0.0 --port 8000" 2>/dev/null && echo "  backend        : dihentikan" || echo "  backend        : tidak jalan"
    pkill -f "uvicorn app.main:app --host 0.0.0.0 --port 8080" 2>/dev/null && echo "  sandbox API    : dihentikan" || echo "  sandbox API    : tidak jalan"
    command -v redis-cli >/dev/null 2>&1 && redis-cli shutdown nosave >/dev/null 2>&1 && echo "  redis          : dihentikan" || echo "  redis          : tidak jalan"
    bash "$REPO/scripts/termux_mongo.sh" stop >/dev/null 2>&1 && echo "  mongodb        : dihentikan" || echo "  mongodb        : tidak jalan"
    command -v termux-wake-unlock >/dev/null 2>&1 && termux-wake-unlock 2>/dev/null
    exit 0
}

do_status() {
    for p in 27017:mongodb 6379:redis 8080:"sandbox API" 8000:backend; do
        port="${p%%:*}"; name="${p#*:}"
        port_up "$port" && echo "  $name  (:${port}) : UP" || echo "  $name  (:${port}) : DOWN"
    done
    exit 0
}

[ "${1:-}" = "stop" ] && do_stop
[ "${1:-}" = "status" ] && do_status

echo "[==] Dzeck AI Agent — start di Termux"

# ── 1. MongoDB ──────────────────────────────────────────────────────────────
if port_up 27017; then
    echo "  mongodb     : sudah jalan (:27017)"
else
    bash "$REPO/scripts/termux_mongo.sh" start && echo "  mongodb     : jalan (:27017)" \
        || echo "  mongodb     : GAGAL — backend masih bisa jalan, tapi riwayat sesi tidak tersimpan"
fi

# ── 2. Redis ────────────────────────────────────────────────────────────────
if port_up 6379; then
    echo "  redis       : sudah jalan (:6379)"
elif command -v redis-server >/dev/null 2>&1; then
    redis-server --daemonize yes --dir "$HOME" >/dev/null 2>&1 \
        && wait_port 6379 redis 10 && echo "  redis       : jalan (:6379)"
else
    echo "  redis       : tidak terpasang — lanjut tanpa redis"
fi

# ── 3. Sandbox API (8080, standalone — tanpa supervisord) ──────────────────
if port_up 8080; then
    echo "  sandbox API : sudah jalan (:8080)"
else
    ( cd "$REPO/sandbox" && \
      SANDBOX_STANDALONE=1 LOG_LEVEL=info nohup "$PY" -m uvicorn app.main:app \
        --host 0.0.0.0 --port 8080 >"$LOGDIR/sandbox.log" 2>&1 & )
    wait_port 8080 "sandbox API" 30 && echo "  sandbox API : jalan (:8080, standalone)"
fi

# ── 3b. Browser opsional (Xvfb + Chrome bila ada) ──────────────────────────
if command -v Xvfb >/dev/null 2>&1 && ! pgrep -f "Xvfb :1" >/dev/null 2>&1; then
    rm -f /tmp/.X1-lock 2>/dev/null
    nohup Xvfb :1 -screen 0 1280x1029x24 >"$LOGDIR/xvfb.log" 2>&1 & sleep 2
    echo "  Xvfb        : jalan (display :1)"
fi
if command -v chromium >/dev/null 2>&1 && port_up 8222; then :;
elif command -v chromium >/dev/null 2>&1 && [ -n "${DISPLAY:-}" ]; then
    nohup chromium --display="${DISPLAY}" --no-sandbox --disable-dev-shm-usage \
        --disable-gpu --user-data-dir="$PREFIX/tmp/chrome-profile" \
        --remote-debugging-address=0.0.0.0 --remote-debugging-port=8222 \
        --remote-allow-origins='*' --no-first-run --no-default-browser-check \
        >"$LOGDIR/chrome.log" 2>&1 & sleep 4
    port_up 8222 && echo "  chromium    : CDP jalan (:8222)" || echo "  chromium    : CDP gagal — tool browser terdegradasi"
else
    echo "  browser     : tidak tersedia — tool browser akan gagal mulai (normal di Termux)"
fi

# ── 4. Backend (8000) ──────────────────────────────────────────────────────
if port_up 8000; then
    echo "  backend     : sudah jalan (:8000)"
else
    [ -f "$REPO/backend/.env" ] || { echo "[!] backend/.env tidak ada — jalankan install_termux.sh dulu." >&2; exit 1; }
    ( cd "$REPO/backend" && set -a && source .env && set +a && \
      nohup "${PYTHON:-python3}" -m uvicorn app.main:app \
        --host 0.0.0.0 --port 8000 >"$LOGDIR/backend.log" 2>&1 & )
    wait_port 8000 backend 60 && echo "  backend     : jalan (:8000)"
fi

# ── Selesai ─────────────────────────────────────────────────────────────────
if port_up 8000; then
    echo ""
    echo "═══ Dzeck AI Agent AKTIF ═══"
    echo "  UI  : http://localhost:8000"
    echo "  API : http://localhost:8000/api/v1  (health: /health)"
    echo "  Log : $LOGDIR/{backend,sandbox}.log"
    echo "  Stop: bash start_termux.sh stop"
else
    echo "[!] backend gagal jalan — cek: tail -50 $LOGDIR/backend.log" >&2
    exit 1
fi
