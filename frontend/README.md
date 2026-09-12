# AI Dzeck Frontend

English | [中文](README_zh.md)

Frontend for AI Dzeck, built with Vue 3 + TypeScript + Vite + Tailwind CSS.

## Features

- Chat interface with task sessions
- Tool panels (Search, Files, Terminal, Browser)
- VNC viewer for real-time sandbox desktop visualization
- Plan panel showing agent step-by-step execution

## Running on Replit

The frontend runs via the **Start application** workflow. Vite dev server starts on port 5000 and proxies all `/api` requests to the backend at `http://localhost:8000`.

No `.env` file needed — backend URL is handled automatically by the Vite proxy config.

```bash
# Install dependencies (if needed)
cd frontend && pnpm install

# Start dev server (port 5000)
pnpm dev

# Build production version
pnpm build

# Type check
pnpm type-check
```

## Project Structure

```
src/
├── assets/          # Static resources and CSS files
├── components/      # Reusable components
│   ├── ChatBox.vue          # Chat input with file attachments
│   ├── ChatMessage.vue      # Chat message rendering
│   ├── LeftPanel.vue        # Session list sidebar
│   ├── ToolPanel.vue        # Tool call visualization panel
│   ├── PlanPanel.vue        # Agent plan steps panel
│   ├── VNCViewer.vue        # noVNC sandbox desktop viewer
│   ├── FilePanel.vue        # File browser panel
│   ├── UserMenu.vue         # User account menu
│   ├── SessionItem.vue      # Session list item
│   ├── filePreviews/        # File preview components (code, image, pdf, etc.)
│   ├── toolViews/           # Tool-specific view components
│   ├── settings/            # Settings components
│   └── ui/                  # Base UI components (reka-ui based)
├── pages/           # Page components
│   ├── ChatPage.vue         # Main chat interface
│   ├── HomePage.vue         # Session list / landing
│   ├── LoginPage.vue        # Login / Register
│   ├── LandingPage.vue      # Public landing page
│   └── SharePage.vue        # Shared session view
├── composables/     # Vue composables (reusable logic)
├── api/             # API client functions
├── types/           # TypeScript type definitions
├── constants/       # App constants
├── locales/         # i18n translations (en + zh)
├── lib/             # Utility libraries
├── utils/           # Helper utilities
├── App.vue          # Root component
└── main.ts          # Entry point
```
