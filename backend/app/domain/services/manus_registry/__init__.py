"""Manus-standard tool registry package.

Single source of truth for the agent tool surface: registry.json (+ 49
standalone tool definitions) copied verbatim from the Manus.im v1.1 export.
The orchestrator gate in ``agents/base.py`` validates every model tool call
against this registry before execution and routes it through the correct
transport executor (MCP vs Shell).
"""
from app.domain.services.manus_registry.loader import (
    get_registry,
    get_tool_def,
    list_tools,
    build_llm_schemas,
    registry_stats,
)
from app.domain.services.manus_registry.errors import (
    ManusToolError,
    error_payload,
    classify_exception,
    redact_secrets,
)
from app.domain.services.manus_registry.schema_validator import validate_arguments
from app.domain.services.manus_registry.trace import LoopSafety, TraceRecorder
from app.domain.services.manus_registry.policy import (
    ConfirmationLedger,
    requires_confirmation,
    confirmation_description,
)

__all__ = [
    "get_registry",
    "get_tool_def",
    "list_tools",
    "build_llm_schemas",
    "registry_stats",
    "ManusToolError",
    "error_payload",
    "classify_exception",
    "redact_secrets",
    "validate_arguments",
    "LoopSafety",
    "TraceRecorder",
    "requires_confirmation",
    "confirmation_payload",
]
