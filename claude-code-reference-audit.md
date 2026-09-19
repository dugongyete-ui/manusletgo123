# Audit — Repository Resmi Claude Code (anthropics/claude-code)

Tanggal: 2026-09-20 · Sifat: read-only · Clone: `--depth 1` ke `/tmp/claude-code-reference`
Versi terbaru di repo (CHANGELOG head): **2.1.278**. Repo TIDAK berisi source CLI — hanya plugins, examples, mods, changelog, docs.

## 1. Pola workflow resmi yang relevan untuk backend Dzeck

- **Agentic loop berbasis tool-use**: model memancarkan tool calls → permission gate → eksekusi tool → `tool_result` → iterasi sampai Stop. Stop hook dapat memblokir penghentian untuk memaksa kelanjutan (`{"decision":"block","reason":...}`) — padanan kami: plan-progress judge + loop advisories.
- **Plan mode**: mode permission first-class (`plan`) — eksplorasi read-only, plan disetujui sebelum eksekusi. Padanan kami: `PlannerAgent.create_plan` + PlanActFlow (plan → execute → update → summarize).
- **Subagents**: agent khusus ber-file `.md`, context window sendiri, toolset dibatasi least-privilege, hasil dikirim kembali dengan header subagent (anti prompt-injection). Padanan kami: `DelegateToolkit` (task_delegate, nested executor).
- **Hooks**: event `PreToolUse`, `PostToolUse`, `UserPromptSubmit`, `Stop`, `SubagentStop`, `SessionStart`, `SessionEnd`, `PreCompact`, `Notification`, `PermissionRequest`; tipe `command` (stdin JSON → exit code / stdout JSON) dan `prompt` (evaluasi LLM). Matcher `"Write|Edit"`, `"*"`, `"mcp__.*"`.
- **Skills**: paket knowledge progressive-disclosure (`SKILL.md` + scripts/references/assets; metadata selalu di context → body saat trigger → resources on demand).
- **MCP**: server eksternal via stdio/HTTP/SSE/WS; config `.mcp.json` / inline `mcpServers`; tool diekspos sebagai `mcp__<server>__<tool>`.
- **Permission modes**: `default` (Manual), `acceptEdits`, `plan`, `bypassPermissions`, `auto`; rule `Bash(git:*)`, `Read(./.env)`; callback SDK `canUseTool`. Padanan kami: `ManusGate` + `ConfirmationLedger` + confirmation endpoint.
- **Streaming & cancellation**: protokol headless `--input-format/--output-format stream-json` (event `init`, per-message, `result` final, `control_request`, interrupt Esc). Padanan kami: SSE contract + `POST /{sid}/stop` + task.cancel().
- **Background agents**: `claude --bg`, agent teams, `SendMessage` lintas session.

## 2–3. Mekanisme plugin/command/agent/skill/hook/MCP & subagent

- Layout plugin: `plugin-name/.claude-plugin/plugin.json` (wajib: `name` kebab-case `^[a-z][a-z0-9]*(-[a-z0-9]+)*$`), dir default `commands/ agents/ skills/ hooks/`, `hooks/hooks.json`, `.mcp.json`.
- Command: Markdown + frontmatter (`description`, `allowed-tools`, `model`, `argument-hint`), body = prompt, `$ARGUMENTS`; namespaced `plugin:command`.
- Agent: `agents/*.md` frontmatter `name/description/model/color/tools`, body = system prompt orang-kedua (20–10k char).
- Skill: `skills/<name>/SKILL.md` frontmatter `name/description` (orang-ketiga), resource on-demand.
- Hook I/O: stdin JSON `{session_id, transcript_path, cwd, permission_mode, hook_event_name, tool_name?, tool_input?}`; output `{continue, suppressOutput, systemMessage}` / `{decision:"approve"|"block", reason}` / `{hookSpecificOutput:{permissionDecision}}`; exit 2 = blok.
- Subagent orchestration resmi: fan-out paralel (code-review: triage→list→summarize→4 reviewer→validator paralel), pipeline berfase (feature-dev: explorer→architect→approval→reviewer).

## 4–5. SDK/API resmi & schema pesan

- Paket resmi: **`@anthropic-ai/claude-agent-sdk`** (npm), **`claude-agent-sdk`** (PyPI, import `claude_agent_sdk`). Legacy `@anthropic-ai/claude-code` deprecated. CLI terbaru 2.1.278. Versi tidak di-pin — guidance resmi: selalu pakai versi terbaru.
- **Programmatic embedding: ya** — dibuktikan in-tree `plugins/security-guidance/hooks/llm.py` (`query(prompt, ClaudeAgentOptions(...))`, `allowed_tools`, `max_turns`, `output_format={"type":"json_schema",...}`, `ResultMessage.structured_output`).
- **⚠️ Temuan kunci**: Python `claude-agent-sdk` pada dasarnya **membungkus CLI Claude Code sebagai subprocess** (stream-json stdin/stdout, `cli_path`, `CLAUDE_CODE_EXECPATH`). Untuk web backend multi-user ini = menjalankan CLI per request — dilarang oleh brief proyek.
- Message types SDK: `AssistantMessage`, `ResultMessage` (`subtype`, `structured_output`, `usage`, `total_cost_usd`), `SystemMessage`; wire: `{type:"user", message:{role,content}}`, event `init`, final `result`, `control_request`, `permission_denials`.
- Content blocks mengikuti Anthropic Messages API (`text`, `tool_use`, `tool_result`).
- **Keputusan**: gunakan **Anthropic Messages API server-side** (SDK `anthropic` / `langchain-anthropic`, endpoint `/v1/messages`) — programatik, tanpa CLI, cocok multi-user. Pola workflow Claude Code diadaptasi, bukan runtime-nya.

## 6–7. MCP config format (resmi)

```jsonc
{ "mcpServers": {
    "fs":    { "command":"npx", "args":["-y","@modelcontextprotocol/server-filesystem","${DIR}"], "env":{...} },
    "api":   { "type":"http", "url":"https://api.example.com/mcp", "headers":{"Authorization":"Bearer ${TOKEN}"} },
    "sse":   { "type":"sse", "url":"https://mcp.example.com/sse" }
}}
```
Ekspansi env `${VAR}`; tool `mcp__<server>__<tool>`. (Format Dzeck: `mcpServers: {name: {command,args,transport:"stdio"|"sse"|"streamable-http",url,enabled,env,headers}}` — setara; Dzeck memakai `transport` eksplisit.)

## 8–9. Risiko lisensi & distribusi

- `LICENSE.md` (verbatim): *"© Anthropic PBC. All rights reserved. Use is subject to Anthropic's Commercial Terms of Service."*
- **All-rights-reserved — bukan open source.** DILARANG menyalin: teks prompt plugin/skill/agent, hook scripts, `mods/` TypeScript, examples, changelog, branding/nama Anthropic.
- Yang aman: **mempelajari** schema/event-name/pattern lalu menulis implementasi orisinal (yang kami lakukan — semua kode integrasi ditulis dari nol di repo Dzeck).
- Klaim "memakai Claude Agent SDK" tanpa import/package nyata dilarang — kami TIDAK mengklaimnya; adapter kami memakai Anthropic Messages API via `langchain-anthropic` (dependency nyata di `pyproject.toml`).

## Yang TIDAK boleh dicopy langsung ke backend FastAPI (lifecycle berbeda)

CLI interactive loop, hooks subprocess (`command` hooks berbasis stdin/stdout CLI), managed settings/MDM, marketplace metadata, plugin bundling — semuanya lifecycle desktop-CLI. Web backend multi-user butuh: model client server-side, event contract SSE sendiri (sudah ada), permission gate in-process (sudah ada: ManusGate), cancellation asyncio (sudah ada).
