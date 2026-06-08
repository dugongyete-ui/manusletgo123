# AI Dzeck × Claw

English | [中文](README_zh.md)

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

AI Dzeck adalah sistem AI Agent serbaguna yang mampu menjalankan berbagai tools dan operasi di dalam lingkungan sandbox. Dilengkapi dengan **Claw** — asisten AI berbasis [OpenClaw](https://github.com/anthropics/openclaw) yang terintegrasi penuh, memberikan pengalaman chat persisten dengan isolasi per-sesi.

## Fitur Utama

- **Tools Lengkap**: Terminal, Browser, File, Web Search, dan integrasi MCP eksternal — semuanya dapat dipantau dan diambil alih secara real-time.
- **AI Model**: Menggunakan **Qwen3.7-max** sebagai model utama via LangChain, dengan dukungan Vision model (**Qwen2.5-VL-72B**) untuk analisis gambar dan screenshot.
- **Sandbox di Replit**: Sandbox berjalan langsung di lingkungan Replit — tidak membutuhkan Docker. Layanan browser (Chrome + VNC), shell, dan file berjalan sebagai proses lokal yang dikelola oleh Supervisord.
- **Sesi & Riwayat**: Manajemen sesi via MongoDB dan Redis, mendukung task di background.
- **Percakapan**: Mendukung stop/interrupt, upload dan download file.
- **Multibahasa**: Mendukung Bahasa Indonesia, Inggris, dan Mandarin.
- **Autentikasi**: Login dan autentikasi user dengan JWT.

## Arsitektur

```
User → Frontend (Vue 3 + Vite)
         ↓ HTTP / SSE
       Backend (FastAPI)
         ↓
       Plan-Act Agent Loop
       ┌─────────────────────────────┐
       │ 1. Planner  → Buat rencana  │
       │ 2. Executor → Jalankan tool │
       │ 3. SSE      → Stream result │
       └─────────────────────────────┘
         ↓
       Sandbox (Replit-native)
       ┌──────────────────────────────────────┐
       │ Chrome + Xvfb + x11vnc + Websockify  │
       │ Shell API · File API · VNC Stream    │
       └──────────────────────────────────────┘
```

## Stack Teknologi

| Lapisan | Teknologi |
|---|---|
| **Frontend** | Vue 3, Vite, Tailwind CSS, TypeScript |
| **Backend** | FastAPI (Python 3.12), LangChain |
| **AI Model** | Qwen3.7-max (chat), Qwen2.5-VL-72B (vision) |
| **Database** | MongoDB (Beanie ODM) |
| **Cache/Queue** | Redis |
| **Sandbox** | Replit-native (Supervisord, Chrome, Xvfb, x11vnc, Websockify) |
| **Search** | Tavily |

## Tools yang Dimiliki Agent

| Tool | Kemampuan |
|---|---|
| **Browser** | Navigasi, klik, ketik, scroll, eksekusi JS (via Playwright / browser_use) |
| **Shell** | Jalankan perintah bash di sandbox |
| **File** | Baca, tulis, cari, dan edit file |
| **Search** | Tavily (default), Bing, Google, Baidu |
| **Image** | Cari dan generate gambar |
| **MCP** | Model Context Protocol — tools extensible |

## Cara Sandbox Bekerja (Replit)

Di Replit, sandbox **tidak menggunakan Docker**. Semua layanan berjalan langsung sebagai proses lokal yang dikelola oleh **Supervisord**:

- **Xvfb** — virtual display (frame buffer)
- **Google Chrome** — browser headless untuk agent
- **x11vnc** — VNC server untuk streaming tampilan browser
- **Websockify** — konversi VNC ke WebSocket agar bisa ditampilkan via NoVNC di frontend
- **Sandbox API** (FastAPI) — menyediakan endpoint untuk Shell, File, dan Browser tool

## Konfigurasi Environment

Semua konfigurasi dikelola via environment variables di Replit:

| Variable | Nilai Saat Ini |
|---|---|
| `MODEL_NAME` | `qwen3.7-max` |
| `MODEL_PROVIDER` | `openai` |
| `API_BASE` | Chat Gateway Replit |
| `VISION_MODEL_NAME` | `qwen2.5-vl-72b-instruct` |
| `MONGODB_URI` | MongoDB Atlas |
| `REDIS_HOST` | Redis Cloud |
| `SEARCH_PROVIDER` | `tavily` |
| `AUTH_PROVIDER` | `password` |
| `SANDBOX_BASE_URL` | `http://localhost:8080` |
| `SANDBOX_CDP_URL` | `http://localhost:8222` |
| `SANDBOX_VNC_URL` | `ws://localhost:5901` |

## Struktur Proyek

```
├── frontend/     # Vue 3 SPA (UI user)
├── backend/      # FastAPI (orkestrasi agent & API)
├── sandbox/      # FastAPI + Supervisord (eksekusi tool lokal)
├── claw/         # OpenClaw plugin (integrasi chat alternatif)
├── mockserver/   # Mock LLM server (untuk development tanpa biaya API)
└── docs/         # Dokumentasi arsitektur & konfigurasi
```

## Alur Pengembangan di Replit

Semua workflow sudah dikonfigurasi otomatis:

- **Start application** — Frontend Vue dev server (port 5000)
- **Backend API** — FastAPI server (port 8000)
- **Sandbox Services** — Supervisord mengelola Chrome, VNC, Sandbox API (port 8080)

Cukup tekan **Run** — semua service berjalan paralel.

## Lisensi

[MIT](LICENSE)
