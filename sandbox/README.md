# AI Dzeck Sandbox Service

English | [中文](README_zh.md)

AI Dzeck Sandbox is an isolated execution environment providing AI Agents with secure Shell command execution, file operations, and browser automation capabilities. On Replit, the sandbox runs **directly via Supervisord** (no Docker required). The service exposes API interfaces through FastAPI.

## Technical Architecture

```
sandbox/
├── app/                   # Main application directory
│   ├── api/               # API interface definitions
│   │   └── v1/            # API version v1
│   │       ├── shell.py   # Shell command execution interface
│   │       ├── file.py    # File operation interface
│   │       └── supervisor.py # Process management interface
│   ├── services/          # Service implementations
│   ├── schemas/           # FastAPI interface models
│   ├── models/            # Data models
│   ├── core/              # Core configurations
│   └── main.py            # Application entry point
├── pyproject.toml              # Python dependencies (uv)
├── supervisord.conf            # Supervisor configuration (Docker)
├── replit_supervisord.conf     # Supervisor configuration (Replit)
└── README.md                   # Documentation
```

## Core Features

1. **Shell Command Execution**: Securely execute Shell commands with session management support
2. **File Operations**: Read, write, search, and manipulate the file system
3. **Browser Environment**:
   - Built-in Google Chrome browser
   - Chrome DevTools Protocol support (CDP)
   - Remote debugging interface on port 8222
4. **VNC Remote Access**:
   - VNC remote desktop service via x11vnc
   - WebSocket interface via websockify (port 5901)
5. **Process Management**: Manage component processes through Supervisord

## Running on Replit

The sandbox is managed by the **Sandbox Services** workflow, which runs:

```bash
cd sandbox && /home/runner/workspace/.pythonlibs/bin/supervisord -n -c replit_supervisord.conf
```

Supervisord manages these processes:
- `xvfb` — virtual display (Xvfb)
- `chrome` — headless Chrome
- `x11vnc` — VNC server
- `websockify` — WebSocket bridge for noVNC (port 5901)
- `app` — FastAPI sandbox API (port 8080)

## Port Information

- **8080**: FastAPI service port
- **8222**: Chrome remote debugging (CDP) port
- **5901**: VNC WebSocket port (via websockify)

## Configuration Options

| Variable | Default | Purpose |
|---|---|---|
| `ORIGINS` | `["*"]` | Allowed CORS origins |
| `SERVICE_TIMEOUT_MINUTES` | unlimited | Auto-terminate after N minutes |
| `LOG_LEVEL` | `INFO` | Log verbosity (`DEBUG`, `INFO`, `WARNING`, `ERROR`) |

## API Documentation

Base URL: `/api/v1`

### 1. Shell-related Endpoints

#### Execute Shell Command
- **Endpoint**: `POST /api/v1/shell/exec`
- **Request Body**: `{"id": "session_id", "exec_dir": "/path", "command": "ls -la"}`

#### View Shell Session Content
- **Endpoint**: `POST /api/v1/shell/view`
- **Request Body**: `{"id": "session_id"}`

#### Wait for Process
- **Endpoint**: `POST /api/v1/shell/wait`
- **Request Body**: `{"id": "session_id", "seconds": 10}`

#### Write Input
- **Endpoint**: `POST /api/v1/shell/write`
- **Request Body**: `{"id": "session_id", "input": "text", "press_enter": true}`

#### Terminate Process
- **Endpoint**: `POST /api/v1/shell/kill`
- **Request Body**: `{"id": "session_id"}`

### 2. File Operation Endpoints

#### Read File
- **Endpoint**: `POST /api/v1/file/read`
- **Request Body**: `{"file": "/abs/path", "start_line": 0, "end_line": 100}`

#### Write File
- **Endpoint**: `POST /api/v1/file/write`
- **Request Body**: `{"file": "/abs/path", "content": "...", "append": false}`

#### Replace File Content
- **Endpoint**: `POST /api/v1/file/replace`
- **Request Body**: `{"file": "/abs/path", "old_str": "...", "new_str": "..."}`

#### Search File Content
- **Endpoint**: `POST /api/v1/file/search`
- **Request Body**: `{"file": "/abs/path", "regex": "pattern"}`

#### Find Files
- **Endpoint**: `POST /api/v1/file/find`
- **Request Body**: `{"path": "/dir", "glob": "*.txt"}`

### 3. Process Management Endpoints

- `GET /api/v1/supervisor/status` — get status of all processes
- `POST /api/v1/supervisor/restart` — restart all services
- `POST /api/v1/supervisor/stop` — stop all services
- `POST /api/v1/supervisor/timeout/activate` — set auto-shutdown timer
- `POST /api/v1/supervisor/timeout/extend` — extend shutdown timer
- `POST /api/v1/supervisor/timeout/cancel` — cancel shutdown timer
- `GET /api/v1/supervisor/timeout/status` — get remaining time

## Debugging

### Check Service Status

```bash
# Via API
curl http://localhost:8080/api/v1/supervisor/status

# Via supervisorctl
cd sandbox && supervisorctl -c replit_supervisord.conf status
```

### Browser Debugging

Access Chrome DevTools at `http://localhost:8222/json` for CDP debugging.
VNC desktop is accessible via the noVNC viewer in the frontend (`VNCViewer.vue`).
