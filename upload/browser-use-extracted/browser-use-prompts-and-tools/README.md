# browser-use — System Prompt & Tools

Ekstraksi dari repo open source https://github.com/browser-use/browser-use
Commit: `50f2055` (9 Sep 2026) · Lisensi: MIT

Isi paket ini **hanya** bagian system prompt dan definisi tools/actions dari agent.

---

## 1. System Prompts — `system_prompts/`

Agent memilih file prompt berdasarkan model & mode (`flash` = mode cepat/hemat,
`no_thinking` = tanpa blok reasoning, `anthropic` = varian khusus Claude).

| File | Baris | Keterangan |
|---|---|---|
| `system_prompt.md` | 270 | **Prompt utama & terlengkap** — mulai di sini |
| `system_prompt_no_thinking.md` | 246 | Varian tanpa reasoning block |
| `system_prompt_anthropic_flash.md` | 247 | Varian Claude + mode flash |
| `system_prompt_flash.md` | 16 | Overlay singkat mode flash |
| `system_prompt_flash_anthropic.md` | 31 | Overlay flash untuk Claude |
| `system_prompt_browser_use*.md` | 15-18 | Overlay untuk model in-house `browser-use` |
| `__init__.py` | — | Logika pemilihan file prompt |

## 2. Perakit Prompt — `agent/prompts.py`

Kelas yang menyusun pesan yang benar-benar dikirim ke LLM:
- `SystemPrompt` — memuat file `.md` di atas
- `AgentMessagePrompt` — merakit state per step: DOM elemen berindeks
  (`[12]<button>Login</button>`), daftar tab, screenshot, isi file system,
  riwayat langkah, hasil aksi sebelumnya.

## 3. Tools / Actions — `tools/`

| File | Isi |
|---|---|
| `service.py` | **Semua definisi tool** (2327 baris) — inti dari paket ini |
| `views.py` | Skema parameter Pydantic tiap tool (yang jadi JSON schema ke LLM) |
| `registry/service.py` | Registry: registrasi, filter per-domain, injeksi dependensi, eksekusi |
| `registry/views.py` | Model data registry + generator schema untuk LLM |
| `extraction/` | Tool `extract` — ekstraksi terstruktur halaman via LLM |
| `utils.py` | Helper |
| `docs/tools.md` | Dokumentasi resmi cara menambah custom tool |

### Daftar tool bawaan

**Navigasi**
- `search` — cari di search engine
- `navigate` — buka URL (opsi tab baru)
- `go_back` — kembali
- `wait` — tunggu N detik

**Interaksi**
- `click` — klik by index, atau by koordinat kalau mode koordinat aktif
- `input` — isi teks ke elemen (default menghapus isi lama)
- `send_keys` — kirim keystroke khusus (Enter, Tab, Escape, kombinasi)
- `scroll` — scroll halaman/kontainer
- `dropdown_options` — baca opsi dropdown
- `select_dropdown` — pilih opsi `<select>`
- `upload_file` — upload file ke input file

**Membaca halaman**
- `extract` — ekstraksi data terstruktur dari halaman pakai LLM
- `search_page` — cari teks/regex di seluruh halaman
- `find_elements` — cari elemen via CSS selector
- `find_text` — scroll ke teks tertentu
- `screenshot` — screenshot viewport
- `save_as_pdf` — simpan halaman jadi PDF
- `evaluate` — jalankan JavaScript di halaman

**Tab**
- `switch` — pindah tab
- `close` — tutup tab

**File system agent**
- `write_file`, `replace_file`, `read_file`

**Selesai**
- `done` — akhiri task (`success`, teks hasil, file lampiran, atau output
  terstruktur sesuai schema yang ditentukan user)

### Cara tool didaftarkan

```python
@self.registry.action(
    'Deskripsi yang dibaca LLM',
    param_model=ClickElementAction,   # skema parameter
    domains=['*.example.com'],        # opsional: batasi per domain
)
async def click(params: ClickElementAction, browser_session: BrowserSession):
    ...
    return ActionResult(extracted_content='...', include_in_memory=True)
```

Deskripsi + `param_model` inilah yang dikonversi jadi JSON schema dan
dikirim ke LLM sebagai daftar tool yang tersedia.

---

Catatan: file `.py` di sini dicabut dari paket aslinya, jadi importnya tidak
akan jalan berdiri sendiri. Untuk menjalankan, `pip install browser-use` atau
clone repo penuh.
