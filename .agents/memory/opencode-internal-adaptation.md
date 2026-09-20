---
name: OpenCode internal adaptation
description: Durable integration decision for using OpenCode patterns without embedding its TypeScript/Bun runtime.
---

Use an internal Python adaptation rather than a CLI subprocess or sidecar:
OpenCode's terminal/server lifecycle is not a safe embedding boundary for the
multi-user FastAPI runtime, and the existing agent already owns the required
session, cancellation, SSE, registry, sandbox, and permission contracts.

**Why:** A second agent loop or storage format would duplicate safety-critical
behavior and make per-user isolation and cancellation harder to prove.

**How to apply:** Keep OpenCode-inspired behavior behind the existing provider
seam and shared dispatch gate. Existing remains the default; any opt-in adapter
must delegate model/tool work to the current runtime and never launch a TUI.