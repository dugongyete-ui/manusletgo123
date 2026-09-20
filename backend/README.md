# AI Dzeck Backend Service

English | [中文](README_zh.md)

AI Dzeck is an intelligent conversation agent system built with FastAPI and LangChain. The backend adopts Domain-Driven Design (DDD) architecture, supporting intelligent dialogue, file operations, shell command execution, browser automation, and web search.

## Project Architecture

The project adopts Domain-Driven Design (DDD) architecture, clearly separating the responsibilities of each layer:

```
backend/
├── app/
│   ├── domain/          # Domain layer: contains core business logic
│   │   ├── models/      # Domain model definitions
│   │   ├── services/    # Domain services
│   │   ├── external/    # External service interfaces
│   │   └── prompts/     # Prompt templates
│   ├── application/     # Application layer: orchestrates business processes
│   │   ├── services/    # Application services
│   │   └── schemas/     # Data schema definitions
│   ├── interfaces/      # Interface layer: defines external system interfaces
│   │   └── api/
│   │       └── routes.py # API route definitions
│   ├── infrastructure/  # Infrastructure layer: provides technical implementation
│   └── main.py          # Application entry
├── pyproject.toml       # Project dependencies and metadata
└── README.md            # Project documentation
```

## Core Features

1. **Session Management**: Create and manage conversation session instances
2. **Real-time Conversation**: Implement real-time conversation through Server-Sent Events (SSE)
3. **Tool Invocation**: Support for various tool calls, including:
   - Browser automation operations (using `browser_use` + Playwright via CDP)
   - Shell command execution and viewing
   - File read/write operations
   - Web search integration (Tavily, Bing, Baidu, DuckDuckGo)
4. **Sandbox Environment**: Replit-hosted sandbox service (Xvfb + Chrome + VNC) at `http://localhost:8080`
5. **VNC Visualization**: Support remote viewing of the sandbox environment via WebSocket connection

## Requirements

- Python 3.12+
- MongoDB Atlas (cloud) or local MongoDB 4.4+
- Redis Cloud (cloud) or local Redis 6.0+

## Installation and Configuration

### On Replit (recommended)

Run `install.sh` from the project root — it installs all Python and frontend dependencies automatically.

### Manual Installation

1. **Install dependencies**:
```bash
pip install -e .
```
Or using uv:
```bash
uv sync
```

2. **Environment variable configuration**:
Copy `.env.example` to `backend/.env` and fill in the values:
```
# LLM provider
API_KEY=your_api_key_here
API_BASE=https://integrate.api.nvidia.com/v1
MODEL_NAME=nvidia/nemotron-3-super-120b-a12b
VISION_MODEL_NAME=meta/llama-3.2-11b-vision-instruct
SSL_VERIFY=false

# Database
MONGODB_URI=mongodb+srv://...
REDIS_HOST=your-redis-host
REDIS_PORT=6379
REDIS_PASSWORD=your-redis-password

# Search
SEARCH_PROVIDER=tavily
TAVILY_API_KEY=your_tavily_key

# Sandbox
SANDBOX_PROVIDER=replit
SANDBOX_BASE_URL=http://localhost:8080
SANDBOX_VNC_URL=ws://localhost:5901
SANDBOX_CDP_URL=http://localhost:8222

# Auth
AUTH_PROVIDER=password
JWT_SECRET_KEY=your-secret-key-here
```

## Running the Service

### Production (z-container, master supervisord)

```bash
/home/z/.venv/bin/supervisorctl -c /home/z/my-project/.infra/master_supervisord.conf restart services:backend
curl -s http://localhost:3000/health   # → 200
```

The backend also serves the compiled frontend from `frontend/dist` on the same port (3000).

### Manual Start
```bash
cd backend
python3 -m uvicorn app.main:app --host 0.0.0.0 --port 3000 --reload
```

The service will start at http://localhost:3000.

## Agent Providers (AGENT_PROVIDER)

The runtime supports swappable **model-provider adapters** behind a stable
seam. The agent loop, tools, sandbox, permission gate, SSE event contract and
cancellation are all provider-agnostic and remain untouched — only the LLM
client layer is swapped.

| `AGENT_PROVIDER` | Adapter | Transport | Default |
|---|---|---|---|
| `existing` | `OpenAICompatProvider` — the configured OpenAI-compatible gateway. **In this deployment: NVIDIA NIM** (`API_BASE=https://integrate.api.nvidia.com/v1`, `MODEL_NAME=nvidia/…`) | server-side HTTP | ✅ default |
| `opencode_adapter` | Native OpenCode-inspired policy/event adapter over the same existing model seam and agent loop | server-side HTTP | opt-in |

**No adapter ever spawns the Claude Code CLI** (or any CLI subprocess) per
request — the web backend requires a programmatically controlled server-side
API. This is enforced by a test (`tests/test_provider_binding_and_contract.py`).

OpenCode is not launched as a TUI, CLI subprocess, or sidecar. The adapter
uses the Python/FastAPI runtime already in this project. It does not copy
OpenCode source and does not create a second session, storage, or tool loop.
The existing Manus registry remains the single tool boundary.

### Running with the existing provider (default — NVIDIA)

```bash
AGENT_PROVIDER=existing   # or simply unset — identical behaviour
# The model itself is configured through the standard settings:
# API_KEY=..., API_BASE=https://integrate.api.nvidia.com/v1, MODEL_NAME=nvidia/...
```

Behaviour notes:

- Unknown `AGENT_PROVIDER` values (including the removed `anthropic`) safely
  **fall back to `existing`** with a warning (chat never breaks).
- `response_format` (OpenAI JSON mode) is supported by the default adapter
  (`supports_response_format=True`) and stays filtered by the capability
  guard for any future adapter.
- Provider errors are classified into a neutral vocabulary
  (`ProviderErrorKind`: AUTH / RATE_LIMIT / TRANSIENT / CONTEXT_OVERFLOW /
  FATAL) so the existing retry ladder — fallback rotation, patient 429
  waiting, context-overflow emergency compaction — works identically.
- The secondary (fallback) provider pool remains the OpenAI-compatible one.
- Session history is projected through `history_adapter.py` — a passthrough
  for the current provider (the NVIDIA gateway consumes LangChain history
  as-is).
- **Rollback**: flip `AGENT_PROVIDER=existing` and restart. No code change.

### OpenCode-inspired mode policy

`AGENT_MODE=build` is the default and preserves the current behavior: every
tool still goes through the existing registry, sandbox, timeout, retry, loop
guard, permission, and confirmation flow.

`AGENT_MODE=plan` is a conservative read-only allowlist. It permits inspection
tools such as `file_read`, `file_list`, search, browser observation, and status
checks. File writes, shell mutation, browser actions, MCP mutation, artifact
creation, and other unlisted tools return an actionable `PERMISSION_DENIED`
ToolResult before dispatch. This policy is enforced in the shared agent
dispatch path, so it also protects legacy tools that are not registry entries.

### Event mapping

The optional `OpenCodeEventNormalizer` maps OpenCode-shaped events into the
existing SSE contract without changing frontend types:

| OpenCode event family | Existing event |
|---|---|
| `message.part.updated`, `message.delta` | `message_chunk` |
| `message.updated` | `message` |
| `tool.execute.before` / `.after` | `tool` (`calling` / `called`) |
| `plan.updated` / `todo.updated` | `plan` |
| `step.*` | `step` |
| `permission.asked` | `wait` |
| `session.error` | `error` |
| `session.idle` / `session.done` | `done` |

Unknown optional events are ignored. Secrets are redacted before normalized
tool arguments/results cross the event boundary.

## MCP (Model Context Protocol) — active by default

MCP servers are configured in `MCP_CONFIG_PATH` (default:
`/home/runner/workspace/mcp.json`; format: see `mcp.json.example` — stdio /
sse / streamable-http, mirroring the official `mcpServers` layout).

**Bootstrap**: when the config file is missing, the backend materialises a
per-environment default config automatically (at startup and before each
run):

| Environment detection | Generated config |
|---|---|
| Replit host (`REPLIT_*` markers) | `dzeck-fs` stdio server, user root `/home/runner/users` |
| E2B runtime markers (`E2B_*`) | `dzeck-fs` stdio server, E2B layout paths |
| z.ai container / local dev | `dzeck-fs` stdio server, user root `USER_HOME_ROOT` |

The bundled server `backend/mcp_servers/filesystem_server.py` is a
self-contained stdio MCP server running on the backend interpreter (no npm
download needed) exposing sandbox-scoped file tools: `list_dir`,
`read_text_file`, `write_text_file`, `create_directory`, `search_files`,
`get_system_info`, `http_get` (SSRF-guarded). Security:

- every path is confined to `DZECK_MCP_USER_ROOT` (per-user home root);
- `DZECK_MCP_PROTECTED` paths (project source) are refused;
- an existing user-owned `mcp.json` is **always respected** — the bootstrap
  never overwrites it;
- bootstrap failures are logged and swallowed — MCP never breaks chat.

Tool calls issued by the model still flow through the Manus registry gate
(`ManusGate` → schema validation → policy/confirmation → MCP/shell
executor), so registry, permissions, timeouts, loop protection and audit
logging stay fully in force for MCP tools.

## API Documentation

Base URL: `/api/v1`

### 1. Create Session

- **Endpoint**: `PUT /api/v1/sessions`
- **Description**: Create a new conversation session
- **Request Body**: None
- **Response**:
  ```json
  {
    "code": 0,
    "msg": "success",
    "data": {
      "session_id": "string"
    }
  }
  ```

### 2. Get Session

- **Endpoint**: `GET /api/v1/sessions/{session_id}`
- **Description**: Get session information including conversation history
- **Path Parameters**:
  - `session_id`: Session ID
- **Response**:
  ```json
  {
    "code": 0,
    "msg": "success",
    "data": {
      "session_id": "string",
      "title": "string",
      "events": []
    }
  }
  ```

### 3. List All Sessions

- **Endpoint**: `GET /api/v1/sessions`
- **Description**: Get list of all sessions
- **Response**:
  ```json
  {
    "code": 0,
    "msg": "success",
    "data": {
      "sessions": [
        {
          "session_id": "string",
          "title": "string",
          "latest_message": "string",
          "latest_message_at": 1234567890,
          "status": "string",
          "unread_message_count": 0
        }
      ]
    }
  }
  ```

### 4. Delete Session

- **Endpoint**: `DELETE /api/v1/sessions/{session_id}`
- **Description**: Delete a session
- **Path Parameters**:
  - `session_id`: Session ID
- **Response**:
  ```json
  {
    "code": 0,
    "msg": "success",
    "data": null
  }
  ```

### 5. Stop Session

- **Endpoint**: `POST /api/v1/sessions/{session_id}/stop`
- **Description**: Stop an active session
- **Path Parameters**:
  - `session_id`: Session ID
- **Response**:
  ```json
  {
    "code": 0,
    "msg": "success",
    "data": null
  }
  ```

### 6. Chat with Session

- **Endpoint**: `POST /api/v1/sessions/{session_id}/chat`
- **Description**: Send a message to the session and receive streaming response
- **Path Parameters**:
  - `session_id`: Session ID
- **Request Body**:
  ```json
  {
    "message": "User message content",
    "timestamp": 1234567890,
    "event_id": "optional event ID"
  }
  ```
- **Response**: Server-Sent Events (SSE) stream
- **Event Types**:
  - `message`: Text message from assistant
  - `title`: Session title update
  - `plan`: Execution plan with steps
  - `step`: Step status update
  - `tool`: Tool invocation information
  - `error`: Error information
  - `done`: Conversation completion

### 7. View Shell Session Content

- **Endpoint**: `POST /api/v1/sessions/{session_id}/shell`
- **Description**: View shell session output in the sandbox environment
- **Path Parameters**:
  - `session_id`: Session ID
- **Request Body**:
  ```json
  {
    "session_id": "shell session ID"
  }
  ```
- **Response**:
  ```json
  {
    "code": 0,
    "msg": "success",
    "data": {
      "output": "shell output content",
      "session_id": "shell session ID",
      "console": [
        {
          "ps1": "prompt string",
          "command": "executed command",
          "output": "command output"
        }
      ]
    }
  }
  ```

### 8. View File Content

- **Endpoint**: `POST /api/v1/sessions/{session_id}/file`
- **Description**: View file content in the sandbox environment
- **Path Parameters**:
  - `session_id`: Session ID
- **Request Body**:
  ```json
  {
    "file": "file path"
  }
  ```
- **Response**:
  ```json
  {
    "code": 0,
    "msg": "success",
    "data": {
      "content": "file content",
      "file": "file path"
    }
  }
  ```

### 9. VNC Connection

- **Endpoint**: `WebSocket /api/v1/sessions/{session_id}/vnc`
- **Description**: Establish a VNC WebSocket connection to the session's sandbox environment
- **Path Parameters**:
  - `session_id`: Session ID
- **Protocol**: WebSocket (binary mode)
- **Subprotocol**: `binary`

## Error Handling

All APIs return responses in a unified format when errors occur:
```json
{
  "code": 400,
  "msg": "Error description",
  "data": null
}
```

Common error codes:
- `400`: Request parameter error
- `404`: Resource not found
- `500`: Server internal error

## Development Guide

### Adding New Tools

1. Define the tool interface in the `domain/external` directory
2. Implement the tool functionality in the `infrastructure` layer
3. Integrate the tool in `application/services`
