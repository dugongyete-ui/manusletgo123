# Laporan Audit & Bug Fix — AI Manus

**Tanggal:** 2026-05-22  
**Status:** ✅ Semua validasi PASSED | Bug kritis diperbaiki

---

## Status Workflow

| Workflow | Status |
|---|---|
| Backend API (FastAPI :8000) | ✅ RUNNING |
| Frontend Vite (:5000) | ✅ RUNNING |
| backend-syntax | ✅ PASSED |
| backend-imports | ✅ PASSED |
| backend-pytest | ✅ PASSED |
| frontend-typecheck | ✅ PASSED |

---

## Teknologi Stack

- **Backend:** Python 3.12 + FastAPI + Beanie (MongoDB) + Redis
- **Frontend:** Vue 3 + Vite + TypeScript + TailwindCSS
- **Sandbox:** E2B (cloud sandbox, menggantikan Docker)
- **LLM:** Cohere (via OpenAI-compat API), mendukung juga OpenAI/Anthropic/DeepSeek
- **Auth:** JWT (password-based), MongoDB user store
- **Arsitektur:** Domain-Driven Design (DDD) — hexagonal architecture

---

## Bug Kritis yang Diperbaiki

### 🔴 FIX-1: CORS Misconfiguration (Keamanan)
**File:** `backend/app/main.py`  
**Masalah:** `allow_origins=["*"]` + `allow_credentials=True` melanggar spesifikasi CORS — browser akan menolak semua response. App ini menggunakan Bearer tokens (bukan cookie), jadi `allow_credentials` tidak diperlukan.  
**Fix:** `allow_credentials=False`

### 🔴 FIX-2: JWT Token-Type Confusion (Keamanan)
**File:** `backend/app/application/services/token_service.py`, `auth_service.py`  
**Masalah:** Endpoint protected menerima refresh token sebagai access token karena `verify_token()` tidak mengecek field `type`.  
**Fix:** Tambah metode `verify_access_token()` yang enforce `type == "access"`. `auth_service.verify_token()` kini menggunakan metode ini.

### 🔴 FIX-3: Password Hash Bocor ke Log (Keamanan)
**File:** `backend/app/application/services/auth_service.py`  
**Masalah:** `_verify_password()` mencetak hash password user di level `INFO` log — siapapun bisa melihatnya di log output.  
**Fix:** Hapus log sensitif, ganti perbandingan string biasa dengan `hmac.compare_digest()` (constant-time, aman dari timing attack).

### 🟠 FIX-4: RuntimeError di Redis Task Destroy
**File:** `backend/app/infrastructure/external/task/redis_task.py`  
**Masalah:** `destroy()` iterasi `_task_registry` dict sambil `task.cancel()` menghapus item dari dict yang sama → `RuntimeError: dictionary changed size during iteration` saat shutdown.  
**Fix:** Snapshot registry dengan `list(cls._task_registry.values())` sebelum iterasi.

### 🟠 FIX-5: _pop_event() Bisa Return None Tanpa Guard
**File:** `backend/app/domain/services/agent_task_runner.py`  
**Masalah:** Return type annotation `AgentEvent` tapi bisa return `None` implisit → downstream code crash non-deterministik.  
**Fix:** Ubah return type ke `Optional[AgentEvent]` dan return `None` eksplisit.

---

## Bug Medium / Warning (Belum Diperbaiki — Tidak Kritis untuk Operasional)

| # | Deskripsi | File | Prioritas |
|---|---|---|---|
| M1 | Race condition warmup sandbox vs chat create (sandbox ganda) | `agent_service.py`, `agent_domain_service.py` | Sedang |
| M2 | Redis stream tidak di-trim → memory leak jangka panjang | `redis_stream_queue.py` | Rendah |
| M3 | `gather(return_exceptions=True)` tapi exceptions diabaikan | `agent_task_runner.py:387` | Sedang |
| M4 | Busy-loop polling `block_ms=0` bisa CPU spin | `agent_domain_service.py:173` | Rendah |
| M5 | `logout()` tidak benar-benar revoke token (placeholder) | `token_service.py:167` | Sedang |
| W1 | TODO: frontend belum handle `WaitEvent` → UI stuck | `ChatPage.vue` | Medium |

---

## Temuan Lain

- **Double-response**: Fix sudah ada di `plan_act.py` (commit sebelumnya) — simple query langsung emit `MessageEvent`, tidak kirim acknowledgment dua kali. ✅ Verified.
- **LSP errors** (`Cannot resolve imported module fastapi`): False positive — LSP tidak punya Python virtual env tapi runtime berjalan normal. ✅ Bukan masalah nyata.
- **E2B Integration**: Fully implemented dengan Chrome auto-install, CDP proxy, path translation. Kode solid.
- **Secrets di `.replit [userenv.shared]`**: API keys tersimpan sebagai plain text di file konfigurasi (E2B_API_KEY, JWT_SECRET_KEY, MONGODB_URI, dll). Disarankan pindah ke Replit Secrets untuk keamanan lebih baik.

---

## Hasil Validasi Akhir

```
backend-syntax    ✅ PASSED  (195ms)
backend-imports   ✅ PASSED  (1401ms)
backend-pytest    ✅ PASSED  (107ms)
frontend-typecheck ✅ PASSED (1044ms)
```

---

## Rekomendasi Selanjutnya

1. **Pindahkan secrets** (API_KEY, E2B_API_KEY, JWT_SECRET_KEY, dll) ke Replit Secrets
2. **Fix race condition sandbox** (M1) — implement session-level lock di `agent_domain_service`
3. **Handle WaitEvent di frontend** — UI harus tampilkan input prompt saat agent menunggu user
4. **Implement token revocation** — simpan revoked tokens di Redis dengan TTL
5. **Trim Redis streams** — tambah `MAXLEN` di XADD command agar memory tidak leak
