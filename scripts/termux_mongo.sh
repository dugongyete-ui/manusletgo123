#!/data/data/com.termux/files/usr/bin/bash
# ═══════════════════════════════════════════════════════════════════════════
# termux_mongo.sh — kelola MongoDB (mongod aarch64 resmi) di dalam
# proot-distro Ubuntu pada Termux. Dipakai oleh install_termux.sh dan
# start_termux.sh — juga bisa dipanggil manual:
#
#   bash scripts/termux_mongo.sh start    # jalankan mongod (idempotent)
#   bash scripts/termux_mongo.sh stop     # matikan mongod
#   bash scripts/termux_mongo.sh status   # port 27017 UP/DOWN
#
# mongod berjalan dengan cache WiredTiger dibatasi 0.25GB agar aman untuk
# RAM ponsel, bind 127.0.0.1 saja (tidak terekspos ke jaringan).
# ═══════════════════════════════════════════════════════════════════════════
set -uo pipefail

if [ -z "${TERMUX_VERSION:-}" ] && [ "${PREFIX:-}" != "/data/data/com.termux/files/usr" ]; then
    echo "[!] termux_mongo.sh khusus Termux." >&2; exit 1
fi

REPO="$(cd "$(dirname "$0")/.." && pwd)"
MONGO_VER="8.0.4"
MONGO_TARBALL="https://fastdl.mongodb.org/linux/mongodb-linux-aarch64-ubuntu2204-${MONGO_VER}.tgz"
LOGDIR="$REPO/logs"; mkdir -p "$LOGDIR"

port_up() { (echo >/dev/tcp/127.0.0.1/"$1") >/dev/null 2>&1; }

find_rootfs() {
    ls -d "$PREFIX"/var/lib/proot-distro/installed-rootfs/ubuntu* 2>/dev/null | head -1
}

find_mongod() {
    # 1) mongod native (kalau user memasangnya sendiri)  2) di dalam proot
    if command -v mongod >/dev/null 2>&1; then
        echo "native"; return 0
    fi
    local rootfs
    rootfs="$(find_rootfs)"
    if [ -n "$rootfs" ] && [ -x "$rootfs/opt/mongodb/bin/mongod" ]; then
        echo "$rootfs/opt/mongodb/bin/mongod"; return 0
    fi
    return 1
}

ensure_installed() {
    local mongod
    mongod="$(find_mongod)" && { echo "$mongod"; return 0; }
    # Belum ada → pasang proot-distro + ubuntu + unduh tarball resmi.
    command -v proot-distro >/dev/null 2>&1 || pkg install -y proot-distro >/dev/null 2>&1
    command -v proot-distro >/dev/null 2>&1 || { echo "[!] proot-distro tidak tersedia" >&2; return 1; }
    if ! proot-distro list 2>/dev/null | grep -q "ubuntu.*: installed"; then
        echo "[==] proot-distro install ubuntu…" >&2
        proot-distro install ubuntu >&2 || return 1
    fi
    local rootfs
    rootfs="$(find_rootfs)"
    [ -n "$rootfs" ] || { echo "[!] rootfs ubuntu tidak ditemukan" >&2; return 1; }
    echo "[==] Mengunduh MongoDB ${MONGO_VER} aarch64 (resmi)…" >&2
    curl -fL --retry 3 -o "$LOGDIR/mongodb.tgz" "$MONGO_TARBALL" >&2 || return 1
    mkdir -p "$rootfs/opt/mongodb" "$rootfs/data/db" "$rootfs/var/log/mongodb"
    tar -xzf "$LOGDIR/mongodb.tgz" -C "$rootfs/opt/mongodb" --strip-components=1 >&2 || return 1
    rm -f "$LOGDIR/mongodb.tgz"
    echo "$rootfs/opt/mongodb/bin/mongod"
}

cmd_start() {
    if port_up 27017; then
        echo "[ok] mongod sudah jalan (:27017)"; return 0
    fi
    local mongod
    mongod="$(ensure_installed)" || { echo "[!] instalasi MongoDB gagal" >&2; return 1; }
    mkdir -p "$LOGDIR"
    if [ "$mongod" = "native" ]; then
        mkdir -p "$HOME/dzeck/mongodb/data" "$HOME/dzeck/mongodb/log"
        nohup mongod --bind_ip 127.0.0.1 --port 27017 \
            --dbpath "$HOME/dzeck/mongodb/data" \
            --pidfilepath "$HOME/dzeck/mongodb/mongod.pid" \
            --logpath "$HOME/dzeck/mongodb/log/mongod.log" \
            --wiredTigerCacheSizeGB 0.25 --fork >/dev/null 2>&1
    else
        local rootfs
        rootfs="$(find_rootfs)"
        echo "[==] Menjalankan mongod di dalam proot (ubuntu)…"
        proot-distro login ubuntu -- bash -c \
            "mkdir -p /data/db /var/log/mongodb && nohup /opt/mongodb/bin/mongod \
             --bind_ip 127.0.0.1 --port 27017 --dbpath /data/db \
             --pidfilepath /data/db/mongod.pid \
             --logpath /var/log/mongodb/mongod.log \
             --wiredTigerCacheSizeGB 0.25 --fork >/dev/null 2>&1" \
            >"$LOGDIR/proot_mongo.log" 2>&1
    fi
    local i=0
    while [ "$i" -lt 30 ]; do
        port_up 27017 && { echo "[ok] mongod jalan (:27017)"; return 0; }
        sleep 1; i=$((i + 1))
    done
    echo "[!] mongod tidak mendengarkan :27017 setelah 30s (log: $LOGDIR/proot_mongo.log)" >&2
    return 1
}

cmd_stop() {
    if command -v mongod >/dev/null 2>&1; then
        mongod --shutdown --dbpath "$HOME/dzeck/mongodb/data" >/dev/null 2>&1
    fi
    local rootfs
    rootfs="$(find_rootfs)"
    if [ -n "$rootfs" ] && [ -x "$rootfs/opt/mongodb/bin/mongod" ]; then
        proot-distro login ubuntu -- bash -c \
            "/opt/mongodb/bin/mongod --shutdown --dbpath /data/db" >/dev/null 2>&1
    fi
    # Fallback terakhir: bunuh proses yang tersisa.
    pkill -f "mongod.*--port 27017" 2>/dev/null
    port_up 27017 && echo "[!] mongod masih jalan" || echo "[ok] mongod berhenti"
}

case "${1:-start}" in
    start)  cmd_start ;;
    stop)   cmd_stop ;;
    status) port_up 27017 && echo "mongodb (:27017) : UP" || echo "mongodb (:27017) : DOWN" ;;
    *) echo "pakai: $0 {start|stop|status}" >&2; exit 2 ;;
esac
