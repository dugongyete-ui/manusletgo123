#!/data/data/com.termux/files/usr/bin/bash
# clean_downloads.sh — hapus semua file sisa runtime (download/foto) dari repo Dzeck.
# Aman dipanggil berulang (idempotent). Tidak menyentuh kode sumber.
# Pakai: bash scripts/clean_downloads.sh

set -u
REPO="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO"

TARGETS=("download" "downloads" "backend/download" "backend/downloads" "tool-results")

TOTAL=0
for t in "${TARGETS[@]}"; do
    if [ -d "$t" ]; then
        N=$(find "$t" -type f 2>/dev/null | wc -l)
        TOTAL=$((TOTAL + N))
        rm -rf "$t"
        echo "hapus $t ($N file)"
    fi
done

echo "Selesai. Total file dihapus: $TOTAL"
