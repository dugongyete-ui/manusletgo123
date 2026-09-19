"""Structured error model for the Manus tool gate.

Every failed tool call returns the same normalized JSON payload to the model:

    {"success": false, "tool": "...", "data": null,
     "error": {"code": "...", "message": "...", "details": {}},
     "retryable": false}

Error codes are part of the contract — the model uses them to decide whether
to repair arguments (VALIDATION_ERROR), pick a different tool (TOOL_NOT_FOUND),
ask the user (REQUIRES_CONFIRMATION), or surface the failure verbatim.
"""
from __future__ import annotations

import re
from typing import Any, Dict, Optional

# ── Error codes ──────────────────────────────────────────────────────────────
class ManusToolError(Exception):
    """Internal executor failure — converted to a structured payload by the
    gate so raw tracebacks never reach the model or the UI."""


VALIDATION_ERROR = "VALIDATION_ERROR"
TOOL_NOT_FOUND = "TOOL_NOT_FOUND"
TOOL_DISABLED = "TOOL_DISABLED"
UNKNOWN_TOOL_ARGUMENT = "UNKNOWN_TOOL_ARGUMENT"
EXECUTION_ERROR = "EXECUTION_ERROR"
TIMEOUT = "TIMEOUT"
TRANSIENT_NETWORK = "TRANSIENT_NETWORK_ERROR"
PERMISSION_DENIED = "PERMISSION_DENIED"
NOT_SUPPORTED = "NOT_SUPPORTED"
CAPABILITY_UNAVAILABLE = "CAPABILITY_UNAVAILABLE"
REQUIRES_CONFIRMATION = "REQUIRES_CONFIRMATION"
LOOP_DETECTED = "LOOP_DETECTED"
MAX_STEPS_REACHED = "MAX_STEPS_REACHED"

# Codes the retry layer may retry (transient classes only).
RETRYABLE_CODES = {TIMEOUT, TRANSIENT_NETWORK}

# Non-retryable: the model must CHANGE something before calling again.
NON_RETRYABLE_CODES = {
    VALIDATION_ERROR,
    TOOL_NOT_FOUND,
    TOOL_DISABLED,
    UNKNOWN_TOOL_ARGUMENT,
    PERMISSION_DENIED,
    NOT_SUPPORTED,
    CAPABILITY_UNAVAILABLE,
    REQUIRES_CONFIRMATION,
    LOOP_DETECTED,
    MAX_STEPS_REACHED,
}

# ── Secret redaction ─────────────────────────────────────────────────────────
_SECRET_KEY_RE = re.compile(
    r"(api[_-]?key|token|secret|password|passwd|authorization|cookie|"
    r"session[_-]?id|credential|private[_-]?key|bearer)",
    re.IGNORECASE,
)
_SECRET_VALUE_RE = re.compile(
    r"(nvapi-[A-Za-z0-9_\-]{10,}|tvly-[A-Za-z0-9_\-]{10,}|sk-[A-Za-z0-9_\-]{10,}|"
    r"e2b_[A-Za-z0-9_\-]{10,}|gh[pousr]_[A-Za-z0-9]{20,}|"
    r"eyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{5,})",  # JWTs
)
_REDACTED = "[REDACTED]"


def redact_secrets(value: Any) -> Any:
    """Recursively redact secret-looking keys and value patterns.

    Applied to every tool result and log line that crosses the gate so
    credentials can never leak into the LLM context, the UI, or the trace.
    """
    if isinstance(value, dict):
        out = {}
        for k, v in value.items():
            if _SECRET_KEY_RE.search(str(k)):
                out[k] = _REDACTED
            else:
                out[k] = redact_secrets(v)
        return out
    if isinstance(value, (list, tuple)):
        return [redact_secrets(v) for v in value]
    if isinstance(value, str):
        return _SECRET_VALUE_RE.sub(_REDACTED, value)
    return value


def error_payload(
    code: str,
    message: str,
    details: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Normalized `error` object with secret redaction applied."""
    return {
        "code": code,
        "message": redact_secrets(message),
        "details": redact_secrets(details or {}),
    }


def success_payload(tool: str, data: Any) -> Dict[str, Any]:
    """Normalized successful tool result."""
    return {
        "success": True,
        "tool": tool,
        "data": redact_secrets(data),
        "error": None,
        "retryable": False,
    }


def failure_payload(
    tool: str,
    code: str,
    message: str,
    details: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Normalized failed tool result (validation errors are never retryable)."""
    return {
        "success": False,
        "tool": tool,
        "data": None,
        "error": error_payload(code, message, details),
        "retryable": code in RETRYABLE_CODES,
    }


def classify_exception(exc: Exception) -> str:
    """Map a raw Python exception to a contract error code."""
    text = str(exc).lower()
    name = type(exc).__name__.lower()
    if "timeout" in name or "timed out" in text or "timeout" in text:
        return TIMEOUT
    if any(
        marker in text
        for marker in (
            "connection reset", "connection refused", "connection error",
            "temporarily unavailable", "server busy", "502", "503", "504",
            "eof occurred", "broken pipe", "dns",
        )
    ):
        return TRANSIENT_NETWORK
    if "permission" in text or "access denied" in text:
        return PERMISSION_DENIED
    if "not found" in text or "no such file" in text:
        return NOT_SUPPORTED
    return EXECUTION_ERROR
