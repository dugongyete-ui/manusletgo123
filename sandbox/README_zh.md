# AI Dzeck 沙盒服务

[English](README.md) | 中文

AI Dzeck Sandbox 是一个隔离执行环境，为 AI Agent 提供安全的 Shell 命令执行、文件操作和浏览器自动化能力。在 Replit 上，沙盒通过 **Supervisord 直接运行**（无需 Docker）。该服务通过 FastAPI 提供 API 接口。

## 技术架构

```
sandbox/
├── app/                   # 应用主目录
│   ├── api/               # API 接口定义
│   │   └── v1/            # API 版本 v1
│   │       ├── shell.py   # Shell 命令执行接口
│   │       ├── file.py    # 文件操作接口
│   │       └── supervisor.py # 进程管理接口
│   ├── services/          # 服务实现
│   ├── schemas/           # FastAPI 接口模型
│   ├── models/            # 数据模型
│   ├── core/              # 核心配置
│   └── main.py            # 应用入口
├── pyproject.toml              # Python 依赖（uv）
├── supervisord.conf            # Supervisor 配置（Docker）
├── replit_supervisord.conf     # Supervisor 配置（Replit）
└── README.md                   # 文档
```

## 核心功能

1. **Shell 命令执行**：安全执行 Shell 命令，支持会话管理
2. **文件操作**：读取、写入、搜索和操作文件系统
3. **浏览器环境**：
   - 内置 Google Chrome 浏览器
   - Chrome DevTools Protocol (CDP) 支持
   - 远程调试接口（端口 8222）
4. **VNC 远程访问**：
   - 通过 x11vnc 提供 VNC 远程桌面服务
   - 通过 websockify 提供 WebSocket 接口（端口 5901）
5. **进程管理**：通过 Supervisord 管理各组件进程

## 在 Replit 上运行

沙盒由 **Sandbox Services** 工作流管理，运行命令：

```bash
cd sandbox && /home/runner/workspace/.pythonlibs/bin/supervisord -n -c replit_supervisord.conf
```

Supervisord 管理以下进程：
- `xvfb` — 虚拟显示器
- `chrome` — 无头 Chrome 浏览器
- `x11vnc` — VNC 服务器
- `websockify` — noVNC WebSocket 桥接（端口 5901）
- `app` — FastAPI 沙盒 API（端口 8080）

## 端口说明

- **8080**：FastAPI 服务端口
- **8222**：Chrome 远程调试（CDP）端口
- **5901**：VNC WebSocket 端口（通过 websockify）

## 配置说明

| 变量 | 默认值 | 用途 |
|---|---|---|
| `ORIGINS` | `["*"]` | 允许的 CORS 来源 |
| `SERVICE_TIMEOUT_MINUTES` | 无限制 | N 分钟后自动终止 |
| `LOG_LEVEL` | `INFO` | 日志级别（`DEBUG`、`INFO`、`WARNING`、`ERROR`） |

## API 接口文档

基础 URL：`/api/v1`

### 1. Shell 相关接口

#### 执行 Shell 命令
- **接口**：`POST /api/v1/shell/exec`
- **请求体**：`{"id": "session_id", "exec_dir": "/path", "command": "ls -la"}`

#### 查看 Shell 会话内容
- **接口**：`POST /api/v1/shell/view`
- **请求体**：`{"id": "session_id"}`

#### 等待进程完成
- **接口**：`POST /api/v1/shell/wait`
- **请求体**：`{"id": "session_id", "seconds": 10}`

#### 写入输入
- **接口**：`POST /api/v1/shell/write`
- **请求体**：`{"id": "session_id", "input": "text", "press_enter": true}`

#### 终止进程
- **接口**：`POST /api/v1/shell/kill`
- **请求体**：`{"id": "session_id"}`

### 2. 文件操作接口

#### 读取文件
- **接口**：`POST /api/v1/file/read`
- **请求体**：`{"file": "/abs/path", "start_line": 0, "end_line": 100}`

#### 写入文件
- **接口**：`POST /api/v1/file/write`
- **请求体**：`{"file": "/abs/path", "content": "...", "append": false}`

#### 替换文件内容
- **接口**：`POST /api/v1/file/replace`
- **请求体**：`{"file": "/abs/path", "old_str": "...", "new_str": "..."}`

#### 搜索文件内容
- **接口**：`POST /api/v1/file/search`
- **请求体**：`{"file": "/abs/path", "regex": "pattern"}`

#### 查找文件
- **接口**：`POST /api/v1/file/find`
- **请求体**：`{"path": "/dir", "glob": "*.txt"}`

### 3. 进程管理接口

- `GET /api/v1/supervisor/status` — 获取所有进程状态
- `POST /api/v1/supervisor/restart` — 重启所有服务
- `POST /api/v1/supervisor/stop` — 停止所有服务
- `POST /api/v1/supervisor/timeout/activate` — 设置自动关闭计时器
- `POST /api/v1/supervisor/timeout/extend` — 延长关闭计时器
- `POST /api/v1/supervisor/timeout/cancel` — 取消关闭计时器
- `GET /api/v1/supervisor/timeout/status` — 获取剩余时间

## 调试指南

### 检查服务状态

```bash
# 通过 API
curl http://localhost:8080/api/v1/supervisor/status

# 通过 supervisorctl
cd sandbox && supervisorctl -c replit_supervisord.conf status
```

### 浏览器调试

通过 `http://localhost:8222/json` 访问 Chrome DevTools 进行 CDP 调试。
VNC 桌面可通过前端的 noVNC 查看器（`VNCViewer.vue`）访问。
