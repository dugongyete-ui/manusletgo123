"""Small, native adaptations of OpenCode concepts for the existing runtime.

This module deliberately does not run OpenCode, import its TypeScript runtime,
or create a second session/tool loop.  It provides:

* a conservative plan-mode policy used before both registry and legacy tool
  dispatch;
* a tolerant normalizer for OpenCode-shaped events when an adapter receives
  them; and
* a structured, redacted tool result for denied mutations.

The actual tool execution remains in the existing Manus registry, sandbox,
permission, retry, timeout, and cancellation pipeline.
"""

from __future__ import annotations

import json
from typing import Any, Dict, Optional

from langchain.messages import ToolMessage

from app.core.config import get_settings
from app.domain.models.event import (
    DoneEvent,
    ErrorEvent,
    MessageChunkEvent,
    MessageEvent,
    PlanEvent,
    PlanStatus,
    StepEvent,
    StepStatus,
    ToolEvent,
    ToolStatus,
    WaitEvent,
)
from app.domain.models.plan import Plan, Step
from app.domain.models.tool_result import ToolResult
from app.domain.services.manus_registry.errors import (
    PERMISSION_DENIED,
    failure_payload,
    redact_secrets,
)


# In plan mode, the safe default is deny.  This is intentionally an allowlist,
# not a heuristic based on a tool name such as "read" or "check".
READ_ONLY_TOOLS = frozenset(
    {
        "file_read",
        "file_list",
        "search_files",
        "browser_view",
        "browser_search_page",
        "browser_find_elements",
        "browser_find_text",
        "browser_find_keyword",
        "browser_console_view",
        "webdev_check_status",
        "message_ask_user",
        "message_update",
        "message_notify_user",
    }
)


def configured_agent_mode() -> str:
    """Return the normalized generic agent policy mode."""
    value = (getattr(get_settings(), "agent_mode", "build") or "build").strip().lower()
    return value if value in {"build", "plan"} else "build"


def is_read_only_mode() -> bool:
    return configured_agent_mode() == "plan"


def is_read_only_tool(tool_name: str) -> bool:
    """Whether a tool is explicitly safe to expose in plan mode."""
    return tool_name in READ_ONLY_TOOLS


def readonly_failure_payload(tool_name: str) -> Dict[str, Any]:
    return failure_payload(
        tool_name,
        PERMISSION_DENIED,
        (
            f"Tool '{tool_name}' is blocked in plan mode. Plan mode is "
            "read-only: inspect, reason, and report findings, but do not "
            "write files, run mutation commands, use browser actions, call "
            "MCP mutations, or change project state. Switch to build mode "
            "for an approved change."
        ),
        {"mode": "plan", "allowed": "explicit read-only allowlist"},
    )


def readonly_tool_message(tool_name: str, tool_call_id: str) -> ToolMessage:
    """Build the same failed ToolMessage shape used by the registry gate."""
    payload = readonly_failure_payload(tool_name)
    return ToolMessage(
        tool_call_id=tool_call_id,
        name=tool_name,
        content=json.dumps(payload, ensure_ascii=False),
        artifact=ToolResult(
            success=False,
            message=payload["error"]["message"],
            data=payload,
        ),
    )


class OpenCodeEventNormalizer:
    """Map common OpenCode event shapes to the existing AgentEvent contract.

    Unknown events return ``None`` so callers can ignore optional upstream
    events without inventing a new frontend event type.
    """

    @staticmethod
    def normalize(raw: Dict[str, Any]) -> Optional[Any]:
        if not isinstance(raw, dict):
            return None
        event_type = str(raw.get("type") or "")
        props = raw.get("properties") or raw.get("data") or {}
        if not isinstance(props, dict):
            props = {}

        if event_type in {"session.idle", "session.completed", "session.done"}:
            return DoneEvent()

        if event_type in {"session.error", "error"}:
            error = props.get("error") or raw.get("error") or props.get("message")
            return ErrorEvent(error=str(redact_secrets(error or "Provider error")))

        if event_type in {"permission.asked", "permission.requested", "session.wait"}:
            return WaitEvent()

        if event_type in {"message.part.updated", "message.chunk", "message.delta"}:
            part = props.get("part") if isinstance(props.get("part"), dict) else props
            content = part.get("text") or part.get("content") or ""
            if isinstance(content, list):
                content = "".join(
                    str(item.get("text", "")) if isinstance(item, dict) else str(item)
                    for item in content
                )
            return MessageChunkEvent(
                role="assistant",
                content=str(content),
                done=bool(part.get("done") or props.get("done")),
            )

        if event_type in {"message.updated", "message.created"}:
            message = props.get("message") if isinstance(props.get("message"), dict) else props
            text = message.get("text") or message.get("content") or ""
            if text:
                return MessageEvent(role="assistant", message=str(text))
            return None

        if event_type in {"tool.execute.before", "tool.started", "tool.call.started"}:
            tool = props.get("tool") or props.get("name") or "unknown"
            args = props.get("args") or props.get("arguments") or {}
            call_id = str(props.get("callID") or props.get("call_id") or "")
            return ToolEvent(
                status=ToolStatus.CALLING,
                tool_call_id=call_id,
                tool_name=str(tool).split("_", 1)[0],
                function_name=str(tool),
                function_args=redact_secrets(args) if isinstance(args, dict) else {},
            )

        if event_type in {"tool.execute.after", "tool.finished", "tool.call.finished"}:
            tool = props.get("tool") or props.get("name") or "unknown"
            args = props.get("args") or props.get("arguments") or {}
            call_id = str(props.get("callID") or props.get("call_id") or "")
            result = props.get("result") if "result" in props else props.get("output")
            return ToolEvent(
                status=ToolStatus.CALLED,
                tool_call_id=call_id,
                tool_name=str(tool).split("_", 1)[0],
                function_name=str(tool),
                function_args=redact_secrets(args) if isinstance(args, dict) else {},
                function_result=redact_secrets(result),
            )

        if event_type in {"plan.updated", "todo.updated"}:
            raw_plan = props.get("plan") if isinstance(props.get("plan"), dict) else props
            try:
                plan = Plan.model_validate(raw_plan)
            except Exception:
                title = str(raw_plan.get("title") or raw_plan.get("goal") or "Plan")
                goal = str(raw_plan.get("goal") or title)
                plan = Plan(title=title, goal=goal)
            return PlanEvent(plan=plan, status=PlanStatus.UPDATED)

        if event_type in {"step.started", "step.updated", "step.completed"}:
            raw_step = props.get("step") if isinstance(props.get("step"), dict) else props
            try:
                step = Step.model_validate(raw_step)
            except Exception:
                step = Step(description=str(raw_step.get("description") or ""))
            status = (
                StepStatus.COMPLETED
                if event_type.endswith("completed")
                else StepStatus.STARTED
            )
            return StepEvent(step=step, status=status)

        return None


def normalize_opencode_event(raw: Dict[str, Any]) -> Optional[Any]:
    """Functional entry point used by adapters and tests."""
    return OpenCodeEventNormalizer.normalize(raw)