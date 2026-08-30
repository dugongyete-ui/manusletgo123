# SKILL.md — Aturan Pengembangan Manus (AI Agent Otonom)

> Dokumen ini adalah KONTRAK PENGEMBANGAN. Wajib dibaca SEBELUM menyentuh
> system prompt, tool docstring, planner, atau agent loop.
> Melanggar aturan di bawah = bug, sekalipun hasilnya sekilas "terlihat membaik".

---

## 1. Prinsip Inti

Ini **AI AGENT OTONOM** (kelas browser-use / Manus.im), **BUKAN AI template**.

- Agent menemukan alur kerjanya SENDIRI dari observasi browser:
  element list, `page_changed`, elemen baru bertanda `*`, hasil verifikasi.
- Tugas user TIDAK BOLEH dibakar ke prompt. Prompt hanya mengajarkan
  CARA BERPIKIR dan CARA BERAKSI secara generik.
- Setiap situs punya alur berbeda. Prompt yang berisi resep tugas justru
  MEMBUTAKAN agent saat situs/nahasnya berbeda — agent mengikuti resep
  padahal realitas di layar berbeda.

---

## 2. LARANGAN KERAS — yang tidak boleh hardcoded di prompt

DILARANG menulis (dalam bentuk APA PUN, termasuk "contoh", "misalnya",
"e.g.", komentar, atau contoh WRONG→RIGHT) di system prompt / execution
prompt / planner prompt / tool docstring:

1. **Nama situs / produk / platform**: Facebook, Instagram, Gmail, Twitter,
   Tokopedia, apa pun. (Sebutan situs di komentar KODE Python untuk
   dokumentasi teknik diperbolehkan — itu bukan string prompt.)
2. **Resep alur tugas**: "ambil email sekali pakai → daftar akun → verifikasi
   kode → posting", "copy email", "masukkan kode verifikasi", "tunggu
   dashboard muncul", dsb. — dalam bahasa apa pun.
3. **Contoh tugas yang menyebut domain**: pendaftaran, kotak masuk, kode
   verifikasi, postingan, checkout, login — semua itu TUGAS, bukan mekanisme.
4. **Environment spesifik** yang bukan bagian dari kontrak tool.

### Yang DIBOLEHKAN (generik — TIPE, bukan TUGAS)

- Aturan interaksi per **tipe widget**: dropdown, combobox, autocomplete,
  tab, modal, hover menu, tabel — karena itu perilaku ENGINE yang sama di
  semua situs (browser-use sendiri memakai ini).
- Disiplin observasi: stale index, `page_changed`, marker elemen baru `*`,
  verifikasi nilai, dua-kali-gagal → ganti strategi.
- Kalibrasi kompleksitas plan (jumlah langkah vs kompleksitas) TANPA contoh
  tugas nyata — pakai bahasa abstrak ("outcome", "phase").
- Bila benar-benar perlu contoh mekanis, pakai placeholder abstrak
  (element, value, page) — jangan pernah alur tugas nyata.

---

## 3. Tool Docstring = Bagian dari Prompt

Docstring tool ikut masuk context LLM (menjadi tool description).
Aturan Bagian 2 berlaku sama. Docstring menjelaskan:
- KAPAN tool dipakai (kondisi, bukan resep tugas)
- APA yang dikembalikan (bentuk data, arti flag)
- APA yang harus dilakukan agent bila gagal (recovery generik)

---

## 4. Protokol Perbaikan Bug

1. **Bukti dulu**: reproduksi / dump session events / log / live test.
   Jangan menebak dari gejala.
2. **Akar masalah**, bukan gejala. Perbaikan minimal & terarah.
3. **Verifikasi**: syntax check + unit test (baseline: 280 pass,
   14 failed + 19 errors adalah pre-existing live-server tests) +
   live test bila menyangkut browser/agent loop
   (`scripts/langgraph_e2e_smoke.py`, `scripts/verify_all_tools.py`).
4. **Commit + push** ke GitHub, tulis worklog di
   `/home/z/my-project/worklog.md`.
5. JANGAN refactor di luar lingkup bug. JANGAN menambah aturan prompt
   baru saat memperbaiki bug non-prompt.

---

## 5. Standar Referensi Prompt = browser-use

Referensi: `/home/z/my-project/browser-use-ref/browser_use/agent/system_prompts/system_prompt.md`

Sifat prompt browser-use (standar yang harus diikuti):
- **100% generik**: nol nama situs, nol resep tugas. Semua aturan berupa
  perilaku engine + disiplin reasoning.
- **Planning by complexity**: "simple (1-3 actions) → act directly;
  complex but clear → 3-10 todo items; complex & unclear → explore first,
  plan once you understand". Plan adalah checklist outcome, bukan transkrip
  instruksi user.
- **Pre-done verification**: sebelum klaim selesai, baca ulang request,
  cek satu per satu requirement, verifikasi aksi benar-benar terjadi di
  halaman. Klaim success hanya bila terbukti.
- **Error recovery**: 2-3 kali gagal → ganti pendekatan; popup/modal
  ditangani dulu; anti-loop eksplisit.

Prompt kita boleh lebih panjang (gaya Manus: narrasi ke user, aturan
komunikasi), tetapi **TIDAK BOLEH lebih spesifik tugasnya** daripada
prompt browser-use. Panjang ≠ resep.

---

## 6. Prinsip Tuning Agent Loop

- **Kesadaran (awareness) > instruksi**: kalau agent berperilaku salah,
  tambahkan INFORMASI yang dikembalikan tool (observasi baru: elemen baru,
  diff, console_logs, verifikasi) — BUKAN instruksi tugas baru.
- **Anti-loop pakai mekanisme**: deteksi repetisi lewat loop detector
  (hash aksi + budget gagal), bukan himbauan di prompt.
- **Result kosong = bug observasi**: setiap tool harus mengembalikan cukup
  data untuk keputusan berikutnya. Kalau agent "tidak sadar", cek dulu
  apa yang tool-nya TIDAK kembalikan.
- Prompt menjawab "bagaimana cara berpikir & bertindak",
  observasi yang menjawab "apa yang sedang terjadi".

---

## 7. Checklist Sebelum Commit yang Menyentuh Prompt

- [ ] `grep -ri "facebook\|instagram\|gmail\|twitter\|signup\|register
       \|email\|inbox\|verification code" backend/app/domain/services/prompts/`
       → hasil hanya boleh berupa aturan generik / kosong.
- [ ] Tidak ada contoh alur tugas di docstring tool:
      `grep -rn "e.g." backend/app/domain/services/tools/` diperiksa manual.
- [ ] Aturan baru bersifat tipe-widget / disiplin observasi / kalibrasi.
- [ ] Unit test tetap lulus baseline.
- [ ] Worklog diperbarui.
