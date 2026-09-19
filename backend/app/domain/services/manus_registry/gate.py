"""Manus registry gate — validates and routes every model tool call.

Inserted into ``BaseAgent.execute()`` BEFORE the legacy toolkit dispatch:

  model tool call
    → registry lookup (name / enabled)
    → JSON-Schema validation of arguments
    → loop-safety (identical call / identical error streaks)
    → confirmation policy (consequential actions)
    → transport routing: mcp → ManusMCPExecutor | shell → ManusShellExecutor
    → normalized ToolMessage (tool_call_id preserved) + trace entry

Tools OUTSIDE the registry (platform-native: message_*, file_*, search_*,
task_delegate, legacy shell_*) return ``None`` from ``process()`` and fall
through to the legacy path untouched — no old feature is removed.

The LLM-facing tool surface is REBUILT from the registry in
``registry_llm_schemas()``: the 31 MCP + 16 shell tools load dynamically,
the 2 documented-unavailable shell tools stay hidden, and platform-native
tools keep their Python schemas. Names never collide (registry wins).
"""
from __future__ import annotations

import logging
import time
from typing import Any, Dict, List, Optional, Tuple

from langchain.messages import ToolMessage

from app.domain.models.tool_result import ToolResult
from app.domain.services.manus_registry.browser_session import BrowserSessionTracker
from app.domain.services.manus_registry.confirmations import confirmation_store
from app.domain.services.manus_registry.errors import (
    TOOL_DISABLED,
    VALIDATION_ERROR,
    failure_payload,
    redact_secrets,
)
from app.domain.services.manus_registry.loader import (
    get_tool_def,
    build_llm_schemas,
    registry_stats,
    tool_available,
)
from app.domain.services.manus_registry.mcp_executor import ManusMCPExecutor
from app.domain.services.manus_registry.notify import (
    CONFIRMATION_REQUIRED,
    TOOL_CALL_FINISHED,
    TOOL_CALL_STARTED,
    ensure_run_started,
    make_event,
    run_registry,
)
from app.domain.services.manus_registry.policy import ConfirmationLedger, requires_confirmation
from app.domain.services.manus_registry.retry import run_with_retry
from app.domain.services.manus_registry.schema_validator import (
    coerce_arguments,
    schema_mentions_brief,
    validate_arguments,
)
from app.domain.services.manus_registry.shell_executor import ManusShellExecutor
from app.domain.services.manus_registry.trace import LoopSafety, TraceRecorder, arguments_hash

logger = logging.getLogger(__name__)


def _toolkit_attr(agent: Any, toolkit_name: str, attr: str) -> Any:
    """Fetch an attribute off a named toolkit instance attached to the agent."""
    for tk in getattr(agent, "toolkits", None) or []:
        if getattr(tk, "name", "") == toolkit_name:
            return getattr(tk, attr, None)
    return None


def _toolkit_event_name(tool_name: str) -> str:
    """UI grouping name (matches existing ToolEvent.tool_name vocabulary)."""
    if tool_name.startswith("browser_"):
        return "browser"
    if tool_name.startswith(("generate_image", "generate_video", "generate_speech", "generate_music")):
        return "image"
    if tool_name.startswith("webdev_"):
        return "shell"
    if tool_name.startswith("manus-"):
        return "shell"
    return "mcp"


class ManusGate:
    """One instance per agent run — holds trace, loop safety, confirmations."""

    def __init__(self, agent: Any) -> None:
        browser = _toolkit_attr(agent, "browser", "browser")
        sandbox = _toolkit_attr(agent, "shell", "sandbox") or _toolkit_attr(
            agent, "file", "sandbox"
        )
        image_toolkit = None
        for tk in getattr(agent, "toolkits", None) or []:
            if getattr(tk, "name", "") == "image":
                image_toolkit = tk
                break
        user_manager = None
        for tk in getattr(agent, "toolkits", None) or []:
            manager = getattr(tk, "manager", None)
            if manager is not None:
                user_manager = manager
                break

        self.trace = TraceRecorder()
        self.safety = LoopSafety()
        # ── Contract context (agent-orchestrator v1.0) ─────────────────
        # task_id/session_id/user_id are stamped onto the agent by the
        # AgentTaskRunner; a missing context (unit tests, replays) falls
        # back to a random task id under the "unknown" session.
        import uuid as _uuid
        ctx = getattr(agent, "task_context", None) or {}
        self.task_id = str(ctx.get("task_id") or _uuid.uuid4().hex[:12])
        self.session_id = ctx.get("session_id")
        self.user_id = ctx.get("user_id")
        try:
            ensure_run_started(
                str(self.session_id or "unknown"),
                self.task_id,
                self.user_id,
            )
        except Exception:  # noqa: BLE001 — events must never break execution
            logger.debug("ensure_run_started failed", exc_info=True)
        self.browser_tracker = BrowserSessionTracker(self.task_id)
        self.confirmations = ConfirmationLedger(task_id=self.task_id)
        self.mcp = ManusMCPExecutor(
            browser=browser,
            sandbox=sandbox,
            image_toolkit=image_toolkit,
            user_mcp_manager=user_manager,
        )
        self.shell = ManusShellExecutor(sandbox) if sandbox is not None else None
        self._user_manager = user_manager
        self._step = 0

    # ── main entry ───────────────────────────────────────────────────────────
    async def process(
        self,
        *,
        tool_name: str,
        tool_call_id: str,
        arguments: Dict[str, Any],
        brief: str = "",
    ) -> Optional[ToolMessage]:
        """Gate one tool call.

        Returns a ToolMessage when the registry governs this tool (executed
        or rejected — the payload ALWAYS reaches the model). Returns None
        when the tool is platform-native and must follow the legacy path.
        """
        tool_def = get_tool_def(tool_name)
        if tool_def is None:
            return None  # platform-native tool → legacy dispatch

        # Backend availability: only hijack a registry tool whose backing
        # implementation is attached. Without the backend the legacy
        # dispatch (mocked in unit tests, real toolkits in production) owns
        # the call — never a silent hijack of a tool we cannot serve.
        if not self._has_backend(tool_name):
            return None

        self._step += 1
        step = self._step
        self._t0 = time.perf_counter()
        self._execution_started = False

        # 1) enabled / available
        if not tool_available(tool_name):
            args_hash = arguments_hash(tool_name, arguments or {})
            payload = failure_payload(
                tool_name, TOOL_DISABLED,
                f"Tool '{tool_name}' is registered but disabled/unavailable "
                "in this deployment (see registry notes).",
            )
            return self._finish(tool_name, tool_call_id, args_hash, payload, brief)

        # 2) argument repair — narration + type slips are fixed BEFORE the
        #    hash and validation so identical operational retries hash the
        #    same and sloppy-but-correctable calls never burn steps:
        #      a) `brief` auto-fill: it is a NARRATION label, not an
        #         operational argument. The registry nests it inside allOf
        #         (browser_click), so the check must scan the WHOLE schema —
        #         a top-level-only check left browser_click unfilled and the
        #         call was rejected 4x in a live session while the model
        #         kept passing everything else correctly.
        #      b) scalar coercion: nemotron-class models send "index": "23"
        #         (string) — jsonschema rejects int-as-string, so coerce
        #         lossless conversions ("23" → 23, "4.5" → 4.5, "true" → true)
        #         when the schema declares that type.
        schema = tool_def.get("input_schema", {})
        arguments = coerce_arguments(schema, dict(arguments or {}))
        if not (arguments).get("brief"):
            if schema_mentions_brief(schema):
                arguments["brief"] = brief or tool_name.replace("_", " ")

        args_hash = arguments_hash(tool_name, arguments)

        # 3) loop safety — identical (tool, args) streak. Runs BEFORE
        #    validation: a model stuck re-sending the same broken call is
        #    exactly the pattern this guard exists for (live session: the
        #    same failing browser_click returned 4x because validation
        #    failures previously bypassed all loop accounting).
        loop_block = self.safety.check_before_execute(tool_name, args_hash)
        if loop_block is not None:
            return self._finish(tool_name, tool_call_id, args_hash, loop_block, brief)

        # 4) schema validation — broken calls NEVER reach executors, and
        #    identical validation failures feed the identical-error streak
        #    so a 3x repeat stops with structured guidance instead of
        #    silently looping forever.
        ok, error = validate_arguments(tool_name, schema, arguments)
        if not ok:
            payload = failure_payload(tool_name, **error)
            err = payload.get("error") or {}
            stop = self.safety.record_error(
                tool_name, err.get("code", VALIDATION_ERROR), str(err.get("message", ""))
            )
            if stop is not None:
                payload = stop
            return self._finish(tool_name, tool_call_id, args_hash, payload, brief)

        # 5) confirmation policy for consequential actions (contract:
        #    confirmation-manager — token + expiry + explicit rejection +
        #    approval that SURVIVES the ask_user pause via the global store)
        if requires_confirmation(tool_def):
            status = confirmation_store.status_for(self.task_id, tool_name, args_hash)
            if status == "rejected":
                payload = self.confirmations.rejected_payload(tool_name, arguments)
                return self._finish(tool_name, tool_call_id, args_hash, payload, brief)
            if status != "approved" and not self.confirmations.is_approved(
                tool_name, arguments
            ):
                conf = confirmation_store.issue(self.task_id, tool_name, arguments)
                payload = self.confirmations.pending_payload(
                    tool_name, tool_def, arguments
                )
                err = payload.setdefault("error", {})
                details = err.setdefault("details", {})
                details["confirmation_token"] = conf["confirmation_token"]
                details["expires_at"] = conf["expires_at"]
                details["approve_via"] = (
                    "POST /api/v1/sessions/{session_id}/confirmations/"
                    f"{conf['confirmation_token']} "
                    "body {\"decision\":\"approved\"|\"rejected\"} — atau "
                    "balas singkat di chat (mis. 'ya' / 'tidak')."
                )
                try:
                    run_registry.emit(
                        make_event(
                            CONFIRMATION_REQUIRED,
                            self.task_id,
                            message=(
                                f"{tool_name} menunggu persetujuan user — "
                                f"expires {conf['expires_at']}"
                            ),
                            step=step,
                            data={
                                "tool": tool_name,
                                "confirmation_token": conf["confirmation_token"],
                                "expires_at": conf["expires_at"],
                            },
                            session_id=self.session_id,
                        )
                    )
                    # Contract task.state-machine.json: confirmation_required
                    # pauses the task (running → waiting_confirmation) until
                    # the approval resumes it.
                    run_registry.pause_run(self.task_id)
                except Exception:  # noqa: BLE001
                    logger.debug("confirmation event failed", exc_info=True)
                return self._finish(tool_name, tool_call_id, args_hash, payload, brief)

        # 6) transport routing — executor-level retry per the retry-error-
        #    handler contract: transient failures (timeout/network) are
        #    retried with exponential backoff BEFORE reaching the model.
        transport = tool_def.get("transport")
        try:
            run_registry.emit(
                make_event(
                    TOOL_CALL_STARTED,
                    self.task_id,
                    message=f"{tool_name} dimulai ({transport})",
                    step=step,
                    data={"tool": tool_name, "transport": transport},
                    session_id=self.session_id,
                )
            )
            # Contract task.state-machine.json: a tool actually executing
            # means the run is running again (waiting_confirmation → running
            # after an approved confirmation).
            run_registry.resume_run(self.task_id)
            self._execution_started = True
        except Exception:  # noqa: BLE001
            logger.debug("tool_call_started event failed", exc_info=True)
        if transport == "shell":
            if self.shell is None:
                payload = failure_payload(
                    tool_name, TOOL_DISABLED,
                    "Shell transport unavailable (sandbox not attached).",
                )
            else:
                payload = await run_with_retry(
                    lambda: self.shell.execute(tool_name, arguments),
                    tool_name=tool_name,
                )
        else:
            payload = await run_with_retry(
                lambda: self.mcp.execute(tool_name, arguments),
                tool_name=tool_name,
            )
            if (
                payload.get("error", {}) or {}
            ).get("code") == "NOT_SUPPORTED" and self._user_manager is not None:
                # Maybe the user's own MCP server implements it (mcp.json).
                payload = await self._try_user_mcp(tool_name, arguments, payload)

        # 6b) browser session state (contract: browser-session-manager) —
        #     active_url / last_view_hash tracked per task for the trace
        #     and the /agent-trace endpoint.
        if tool_name.startswith("browser_"):
            try:
                self.browser_tracker.observe(tool_name, arguments, payload)
            except Exception:  # noqa: BLE001
                logger.debug("browser tracker observe failed", exc_info=True)

        # 6c) tool_call_finished event (contract notification-event-bus)
        try:
            run_registry.emit(
                make_event(
                    TOOL_CALL_FINISHED,
                    self.task_id,
                    message=(
                        f"{tool_name} {'sukses' if payload.get('success') else 'gagal'}"
                    ),
                    step=step,
                    data={
                        "tool": tool_name,
                        "success": bool(payload.get("success")),
                        "error_code": (payload.get("error") or {}).get("code"),
                        "duration_ms": int((time.perf_counter() - self._t0) * 1000),
                    },
                    session_id=self.session_id,
                )
            )
        except Exception:  # noqa: BLE001
            logger.debug("tool_call_finished event failed", exc_info=True)

        # 7) bookkeeping
        if payload.get("success"):
            self.safety.record_success()
        else:
            err = payload.get("error") or {}
            stop = self.safety.record_error(
                tool_name, err.get("code", "EXECUTION_ERROR"), str(err.get("message", ""))
            )
            if stop is not None:
                payload = stop
        return self._finish(tool_name, tool_call_id, args_hash, payload, brief)

    def _has_backend(self, tool_name: str) -> bool:
        """Whether the backing implementation for this tool is attached."""
        if tool_name.startswith("browser_"):
            return self.mcp._browser is not None
        if tool_name in ("generate_image", "generate_image_variation"):
            return self.mcp._image_toolkit is not None
        if tool_name.startswith(("generate_video", "generate_speech", "generate_music")):
            return True  # handled explicitly (structured NOT_SUPPORTED)
        if tool_name.startswith("webdev_"):
            return self.mcp._sandbox is not None
        if tool_name.startswith("manus-"):
            return self.shell is not None
        return True

    async def _try_user_mcp(
        self, tool_name: str, arguments: Dict[str, Any], current: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Fall back to the user's own MCP servers for registry tools the
        builtin executor does not implement."""
        try:
            tr: ToolResult = await self._user_manager.call_tool(tool_name, arguments)
        except Exception as exc:  # noqa: BLE001
            logger.debug("user MCP fallback failed for %s: %s", tool_name, exc)
            return current
        if tr is None:
            return current
        data: Dict[str, Any] = {"message": tr.message}
        if isinstance(tr.data, dict):
            data.update(tr.data)
        from app.domain.services.manus_registry.errors import success_payload as _sp
        return _sp(tool_name, redact_secrets(data)) if tr.success else current

    # ── result packaging ─────────────────────────────────────────────────────
    def _finish(
        self,
        tool_name: str,
        tool_call_id: str,
        args_hash: str,
        payload: Dict[str, Any],
        brief: str,
    ) -> ToolMessage:
        """Normalize payload → ToolMessage + trace entry (+ error bookkeeping)."""
        import json as _json

        success = bool(payload.get("success"))
        err = payload.get("error") or {}
        duration_ms = int((time.perf_counter() - getattr(self, "_t0", time.perf_counter())) * 1000)
        _tool_def = get_tool_def(tool_name)
        entry = self.trace.record(
            step=self._step,
            tool=tool_name,
            args_hash=args_hash,
            success=success,
            duration_ms=duration_ms,
            error_code=err.get("code"),
            transport=_tool_def.get("transport") if _tool_def else None,
            task_id=self.task_id,
            conversation_id=self.session_id,
        )
        try:
            run_registry.record_trace(self.task_id, entry)
        except Exception:  # noqa: BLE001
            logger.debug("run registry trace failed", exc_info=True)
        if getattr(self, "_execution_started", False):
            entry["browser_state"] = self.browser_tracker.snapshot()
        payload.setdefault("trace", {
            "step": entry["step"],
            "arguments_hash": args_hash,
            "duration_ms": duration_ms,
        })
        state_changed = self._infer_state_changed(tool_name, payload)
        if state_changed is not None:
            entry["state_changed"] = state_changed

        artifact = ToolResult(
            success=success,
            message=(err.get("message") if not success else None)
            or _json.dumps(payload.get("data"), ensure_ascii=False)[:2000],
            data=payload.get("data"),
        )
        content = _json.dumps(payload, ensure_ascii=False, default=str)
        from app.domain.services.tools.base import cap_tool_content
        try:
            from app.core.config import get_settings as _gs
            limit = int(getattr(_gs(), "tool_result_max_chars", 48_000) or 0)
        except Exception:
            limit = 48_000
        return ToolMessage(
            tool_call_id=tool_call_id,
            name=tool_name,
            content=cap_tool_content(content, limit),
            artifact=artifact,
        )

    @staticmethod
    def _infer_state_changed(tool_name: str, payload: Dict[str, Any]) -> Optional[bool]:
        """Best-effort state-change signal for the trace (browser mutations)."""
        if not payload.get("success"):
            return False
        data = payload.get("data") or {}
        if tool_name in ("browser_navigate", "browser_click", "browser_input",
                          "browser_fill_form", "browser_select_option",
                          "browser_press_key", "browser_upload_file"):
            if isinstance(data, dict) and "page_changed" in data:
                return bool(data["page_changed"])
            return True
        if tool_name.startswith(("file_", "webdev_", "manus-")):
            return True
        return None


# ── LLM surface rebuild ──────────────────────────────────────────────────────

def registry_llm_schemas(agent: Any) -> List[Dict[str, Any]]:
    """Final OpenAI tool schemas for an agent in registry mode.

    - All ENABLED registry tools (31 MCP + 16 shell) load dynamically.
    - Platform-native tools not in the registry keep their Python schemas
      (brief still injected by the caller for narration discipline).
    - Registry names WIN over Python duplicates (no double definition).
    """
    registry_names = set()
    out: List[Dict[str, Any]] = []
    for schema in build_llm_schemas():
        registry_names.add(schema["function"]["name"])
        out.append(schema)

    try:
        from langchain_core.utils.function_calling import convert_to_openai_tool
        from app.domain.services.agents.base import _with_brief_parameter
        for tool in agent.get_tools():
            if tool.name in registry_names:
                continue
            try:
                schema = convert_to_openai_tool(tool)
                function = schema.get("function", {})
                function["parameters"] = _with_brief_parameter(
                    function.get("parameters")
                )
                out.append(schema)
            except Exception:  # noqa: BLE001
                out.append(tool)
    except Exception:  # noqa: BLE001
        pass
    return out


def gate_stats() -> Dict[str, int]:
    """Registry counts for health endpoints / debug panels."""
    return registry_stats()
