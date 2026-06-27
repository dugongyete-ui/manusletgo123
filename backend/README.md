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
API_BASE=https://your-llm-gateway/v1
MODEL_NAME=kimi-k2
VISION_MODEL_NAME=kimi-k2

# Database
MONGODB_URI=mongodb+srv://...
REDIS_HOST=your-redis-host
REDIS_PORT=6379
REDIS_PASSWORD=your-redis-password

# Search
SEARCH_PROVIDER=tavily
TAVILY_API_KEY=your_tavily_key

# Sandbox
SANDBOX_BASE_URL=http://localhost:8080
SANDBOX_VNC_URL=ws://localhost:5901
SANDBOX_CDP_URL=http://localhost:8222

# Auth
AUTH_PROVIDER=password
JWT_SECRET_KEY=your-secret-key-here
```

## Running the Service

### Development Environment (Replit)

The **Backend API** workflow starts the server automatically:
```bash
cd backend && python3 -m uvicorn app.main:app --host localhost --port 8000
```

### Manual Start
```bash
cd backend
python3 -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

The service will start at http://localhost:8000.

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
