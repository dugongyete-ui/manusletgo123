# Dzeck AI Agent di Termux (Android)

> Bahasa deployment: **Termux** adalah lingkungan ke-4 yang didukung proyek ini,
> di samping **Replit**, **E2B**, dan **z.ai**. Deteksi lingkungan otomatis:
> `backend/app/domain/services/mcp/environment.py` → `detect_environment()`
> mengembalikan `"termux"` bila `TERMUX_VERSION` ada atau `$PREFIX` berujung
> `com.termux.files/usr`.

---

## 1. Instalasi sekali-jalan

Prasyarat: **Termux dari F-Droid** (bukan Play Store — versi Play Store usang),
Android 8+, ±2 GB ruang bebas, koneksi internet. Lalu:

```bash
pkg update -y && pkg install -y git
git clone https://github.com/dugongyete-ui/manusletgo123.git
cd manusletgo123
bash install_termux.sh
```

Skrip `install_termux.sh` melakukan semuanya sekali jalan:

| Tahap | Isi | Catatan |
|---|---|---|
| 1 | `pkg install` toolchain build (clang, rust, cmake, ninja…) + runtime (python, nodejs, redis, proot-distro) + paket Python prebuilt Termux (numpy, cryptography, psutil, pillow, lxml) | beberapa menit |
| 2 | virtualenv `.venv` (`--system-site-packages` → memakai numpy bawaan Termux) | cepat |
| 3 | pydantic-core **dibangun dari sumber** via maturin (Rust) | 5–15 menit |
| 4 | pandas & curl-cffi (build berat; bila gagal → **degradasi fungsional**, bukan gagal total) | 20–45 menit |
| 5 | seluruh dependensi backend (`pip install -e backend`) + deps test | 5–10 menit |
| 6 | **MongoDB resmi aarch64 8.0** di dalam proot-distro Ubuntu, `localhost:27017` | unduh ±90 MB |
| 7 | frontend `npm install && npm run build` → `frontend/dist` (disajikan backend) | 2–5 menit |
| 8 | `backend/.env` default Termux (isi `API_KEY` NVIDIA milikmu!) | — |

Setelah selesai:

```bash
nano backend/.env          # isi API_KEY (NVIDIA NIM)
bash start_termux.sh       # mongo + redis + sandbox API + backend
```

Aplikasi siap di **http://localhost:8000** (UI + API satu port).

## 2. Perintah harian

```bash
bash start_termux.sh          # start semua (idempotent — service yang sudah jalan dilewati)
bash start_termux.sh stop     # matikan semua
bash start_termux.sh status   # cek :27017 / :6379 / :8080 / :8000
bash scripts/termux_mongo.sh {start|stop|status}
tail -50 logs/backend.log     # log backend
tail -50 logs/sandbox.log     # log sandbox API
```

## 3. Apa yang BERBEDA di Termux (peta mismatch yang sudah ditutup)

| Aspek | Replit / z.ai / E2B | Termux |
|---|---|---|
| Arsitektur | amd64 (glibc) | **aarch64 (Bionic libc)** — wheel PyPI glibc tak terpasang; paket berat dari repo Termux atau build sumber |
| Paket manager OS | apt / nix | **`pkg`** — prompt agent mengajari ini |
| MongoDB | service tersedia | **tidak ada paket** → mongod resmi dijalankan dalam `proot-distro` Ubuntu (network sama → `localhost:27017`) |
| Supervisord | mengelola Xvfb/Chrome/VNC/sandbox | **tidak ada** → sandbox API jalan `SANDBOX_STANDALONE=1`; status supervisor mengembalikan proses `app` sintetis RUNNING |
| Sandbox id | `replit-local` / `e2b:<id>` | **`termux-local`** (`TermuxSandbox`, provider `termux`) |
| System prompt agent | "Ubuntu/Debian amd64, /home/runner…" | **"Android aarch64 + Termux, $PREFIX, pkg, tanpa sudo/FHS"** — prompt jujur sesuai host |
| Browser/VNC | Chrome + Xvfb + x11vnc wajib | **opsional** — bila Xvfb/chromium terpasang, `start_termux.sh` menyalakannya; bila tidak, tool browser gagal per-panggilan secara mulai |
| E2B | fallback / pilihan | host guard: default **100% lokal**; `SANDBOX_PROVIDER=e2b` eksplisit untuk memaksa cloud |

Kode yang menyentuh Termux (semua penambahan, tanpa mengubah jalur Replit/E2B/z.ai):

- `backend/app/domain/services/mcp/environment.py` — deteksi `"termux"` (+ guard di sandbox factory);
- `backend/app/infrastructure/external/sandbox/termux_sandbox.py` — sandbox lokal Termux (subclass `ReplitSandbox`);
- `backend/app/infrastructure/external/sandbox/sandbox_factory.py` — `_local_sandbox_cls()` + host guard Termux;
- `backend/app/domain/services/prompts/system.py` — blok `<sandbox_environment>` + `<security_rules>` khusus Termux;
- `sandbox/app/services/supervisor.py` — mode standalone fail-open (tanpa supervisord);
- `backend/app/infrastructure/external/search/__init__.py` — degradasi mulai saat `curl_cffi` tak terpasang.

## 4. Batasan yang diketahui (jujur)

1. **Build berat butuh waktu & baterai** — pydantic-core/pandas dikompilasi di ponsel.
   Pasang pengisi daya, jangan matikan layar (`termux-wake-lock` otomatis aktif).
2. **RAM**: build pydantic-core butuh ±2 GB. Tutup aplikasi besar bila proses
   terbunuh (`Killed`), lalu jalankan ulang `install_termux.sh` (idempotent).
3. **Browser/live-view**: termasuk opsional. Tool browser akan melapor error
   koneksi bila Chrome tak jalan — agent diberi tahu lewat prompt untuk
   melanjutkan dengan shell/file. Untuk memakai browser, pasang `x11-repo`,
   `xvfb`, `x11vnc` (installer mencoba otomatis) dan Chromium dari sumber
   komunitas Termux, lalu `start_termux.sh` mendeteksinya sendiri.
4. **curl-cffi gagal build** → search scraping (bing_web/bing_rss/baidu_web)
   dinonaktifkan otomatis; pakai `SEARCH_PROVIDER=tavily` (API murni) di `.env`.
5. **pandas gagal build** → analisa berkas `.xlsx` tetap jalan via `openpyxl`;
   tool data yang butuh pandas akan melapor error mulai.
6. Performa inferensi bergantung jaringan ke NVIDIA NIM — model tidak jalan di ponsel.

## 5. Troubleshooting cepat

| Gejala | Solusi |
|---|---|
| `pkg install` 404 / gagal mirror | `termux-change-repo` → pilih mirror Mirror Group/TUNA, ulangi |
| Build `Killed` saat maturin/pandas | RAM habis — tutup aplikasi, ulangi skrip (sudah ter-cache tahap sebelumnya) |
| Backend mati saat layar mati | `termux-wake-lock` (otomatis via skrip) + matikan optimasi baterai untuk Termux |
| `mongod tidak mendengarkan :27017` | `bash scripts/termux_mongo.sh start`; cek `logs/proot_mongo.log`; proot-distro butuh ±500 MB bebas |
| Port 8000/8080 dipakai | `bash start_termux.sh stop` dulu, atau `pkill -f uvicorn` |
| Lupa isi API key | `nano backend/.env` → `API_KEY=...` → restart backend |
