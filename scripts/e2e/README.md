# E2E Test Infrastructure

Infrastruktur E2E yang mereplikasi lingkungan runtime Replit secara lokal:
supervisord menjalankan Xvfb + Chromium (CDP) + websockify + sandbox API (:8080),
backend berjalan di :8000, lalu driver mengirim pesan chat nyata ke AI agent
dan merekam seluruh event SSE untuk analisis bug (double-send file, drop
summary, loop agent, dll).

## Komponen

| File | Fungsi |
|------|--------|
| `run_e2e.sh` | Orkestrator satu-sesi: naikkan stack, jalankan driver, bersihkan semua proses |
| `e2e_supervisord.conf` | Konfigurasi supervisord (Xvfb :1, Chrome CDP :8222, websockify :5901, sandbox :8080) |
| `e2e_driver.py` | Driver SSE — register user, buat session, POST chat, rekam semua event ke JSONL + snapshot MongoDB |
| `test_browser_e2e.py` | 16 pengujian browser tools nyata (Pola A/C/D dari laporan QA) melalui CDP |
| `browser_test_page/` | Halaman HTML uji (dropdown, login form) untuk `test_browser_e2e.py` |

## Prasyarat

1. Dependencies terpasang (`install.sh` di root repo).
2. `backend/.env` berisi kredensial yang valid (MongoDB, Redis, OpenRouter API key).
3. Chrome/Chromium tersedia — default: binary Playwright di
   `~/.cache/ms-playwright/chromium-*/chrome-linux64/chrome` (atau set `CHROME_BIN`).

## Menjalankan E2E penuh (chat ke AI agent)

```bash
E2E_MESSAGE="Uji semua kemampuan anda tools yang tersedia..." \
E2E_NEW_SESSION=1 \
bash scripts/e2e/run_e2e.sh
```

Output: `scripts/e2e/out/` berisi `e2e_events.jsonl` (semua event SSE),
`e2e_summary.json` (ringkasan run: tool calls, pesan, attachments, ended_with),
dan `e2e_session_snapshot.json` (state session dari MongoDB).

Indikator bug yang dipantau driver:
- `ended_with` harus `done` (bukan `stream_closed` / `timeout` / `error`)
- `MESSAGES WITH ATTACHMENTS` — file harus muncul pada PERSIS SATU pesan
  (deteksi double-send file MD)
- setiap tool call berstatus sukses

## Menjalankan browser tools test saja

```bash
# terminal 1: halaman uji
cd scripts/e2e/browser_test_page && python3 -m http.server 8900

# terminal 2: chrome dengan CDP (atau start supervisord via run_e2e.sh)
bash scripts/e2e/run_e2e.sh   # lalu Ctrl-C setelah chrome siap, atau jalankan chrome manual

# terminal 3: test
python3 scripts/e2e/test_browser_e2e.py
```

## Variabel lingkungan

| Var | Default | Keterangan |
|-----|---------|------------|
| `E2E_MESSAGE` | prompt QA bawaan | Pesan yang dikirim ke agent |
| `E2E_TIMEOUT` | `420` | Batas waktu keseluruhan (detik) |
| `E2E_NEW_SESSION` | `0` | `1` = buat session chat baru |
| `E2E_NO_SEND` | `0` | `1` = hanya ambil state session existing |
| `E2E_PYTHON` | venv python | Interpreter untuk backend & driver |
| `E2E_VENV_BIN` | `$HOME/.venv/bin` | Direktori bin venv untuk supervisord |
| `E2E_BACKEND` | `http://localhost:8000/api/v1` | Base URL backend |
| `E2E_OUT_DIR` | `scripts/e2e/out` | Direktori artefak output |
| `CHROME_BIN` | auto-detect Playwright | Binary Chrome untuk supervisord |

## Catatan deviasi dari Replit asli

- `x11vnc` tidak tersedia tanpa sudo di lingkungan pengujian — preview VNC
  tidak diperlukan untuk testing agent (browser tools memakai CDP :8222).
- Sandbox services memakai supervisord konfigurasi ini, bukan
  `sandbox/replit_supervisord.conf` (yang memakai path `/home/runner/workspace`).
- Model default OpenRouter yang terverifikasi bekerja dengan tool-calling:
  `nvidia/nemotron-3-super-120b-a12b:free` (model `stealth/ox-alpha` sudah
  dihentikan OpenRouter per 2026-08-26).
