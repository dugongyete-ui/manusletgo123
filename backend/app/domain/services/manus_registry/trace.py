"""Loop safety + structured trace for the Manus agent loop.

Per-task state:
  - trace entries: {step, tool, arguments_hash, success, state_changed,
    duration_ms, retry_count, error_code} — one per tool call, queryable
    for debugging.
  - identical-call detection: (tool, args_hash) repetition counting;
    >= IDENTICAL_CALL_LIMIT consecutive repeats raises LOOP_DETECTED so the
    model is forced to change strategy instead of burning the step budget.
  - identical-error detection: the same error signature 3 times in a row
    stops the loop with a structured result.
"""
from __future__ import annotations

import hashlib
import json
import logging
import time
from collections import Counter
from typing import Any, Dict, List, Optional

from app.domain.services.manus_registry.errors import LOOP_DETECTED

logger = logging.getLogger(__name__)

IDENTICAL_CALL_LIMIT = 3
IDENTICAL_ERROR_LIMIT = 3
TRACE_MAX_ENTRIES = 500


def arguments_hash(tool_name: str, arguments: Dict[str, Any]) -> str:
    """Stable hash of tool name + arguments (for loop detection + traces)."""
    try:
        canonical = json.dumps(
            {"tool": tool_name, "args": arguments},
            sort_keys=True, ensure_ascii=False, default=str,
        )
    except Exception:  # pragma: no cover
        canonical = f"{tool_name}:{str(arguments)[:500]}"
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]


class TraceEntry(dict):
    """Plain dict with known keys — kept as dict so it is JSON-serializable."""


class TraceRecorder:
    """Append-only structured trace for one agent run."""

    def __init__(self) -> None:
        self.entries: List[Dict[str, Any]] = []

    def record(
        self,
        step: int,
        tool: str,
        args_hash: str,
        success: bool,
        duration_ms: int,
        error_code: Optional[str] = None,
        retry_count: int = 0,
        state_changed: Optional[bool] = None,
        transport: Optional[str] = None,
        task_id: Optional[str] = None,
        conversation_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        entry = {
            "step": step,
            "tool": tool,
            "transport": transport,
            "arguments_hash": args_hash,
            "success": success,
            "state_changed": state_changed,
            "duration_ms": duration_ms,
            "error_code": error_code,
            "retry_count": retry_count,
            "start_time": time.time() - duration_ms / 1000.0,
        }
        if task_id:
            entry["task_id"] = task_id
        if conversation_id:
            entry["conversation_id"] = conversation_id
        self.entries.append(entry)
        if len(self.entries) > TRACE_MAX_ENTRIES:
            self.entries = self.entries[-TRACE_MAX_ENTRIES:]
        # Structured observability log line (secret-free by construction —
        # only names/hashes/codes are logged, never arguments or results).
        logger.info(
            "manus_tool_trace step=%s tool=%s transport=%s hash=%s success=%s "
            "state_changed=%s duration_ms=%s error=%s retries=%s",
            step, tool, transport, args_hash, success, state_changed,
            duration_ms, error_code, retry_count,
        )
        return entry

    def last(self) -> Optional[Dict[str, Any]]:
        return self.entries[-1] if self.entries else None


class LoopSafety:
    """Detects non-progress tool-call patterns within one agent run."""

    def __init__(self) -> None:
        # consecutive repetition counts per (tool, args_hash)
        self._streak: Counter = Counter()
        self._last_hash: Optional[str] = None
        self._error_streak: Counter = Counter()
        self._last_error_sig: Optional[str] = None
        self.blocked_message: Optional[str] = None

    def check_before_execute(self, tool_name: str, args_hash: str) -> Optional[Dict[str, Any]]:
        """Return a LOOP_DETECTED failure payload when the model is about to
        repeat an identical (tool, args) call beyond the allowed streak."""
        if self._last_hash == args_hash:
            self._streak[args_hash] += 1
        else:
            self._streak.clear()
            self._streak[args_hash] = 1
            self._last_hash = args_hash
        if self._streak[args_hash] >= IDENTICAL_CALL_LIMIT:
            self.blocked_message = (
                f"Identical call repeated {self._streak[args_hash]}x "
                f"(hash {args_hash})."
            )
            return failure_loop_payload(tool_name, self.blocked_message)
        return None

    def record_error(self, tool_name: str, error_code: str, message: str) -> Optional[Dict[str, Any]]:
        """Track consecutive identical failures; returns stop payload at limit."""
        sig = f"{tool_name}:{error_code}:{hashlib.sha256(message.encode()).hexdigest()[:12]}"
        if self._last_error_sig == sig:
            self._error_streak[sig] += 1
        else:
            self._error_streak.clear()
            self._error_streak[sig] = 1
            self._last_error_sig = sig
        if self._error_streak[sig] >= IDENTICAL_ERROR_LIMIT:
            return failure_loop_payload(
                tool_name,
                f"Identical error ({error_code}) occurred "
                f"{self._error_streak[sig]}x in a row without progress.",
            )
        return None

    def record_success(self) -> None:
        """Any successful call resets the error streak."""
        self._error_streak.clear()
        self._last_error_sig = None


def failure_loop_payload(tool_name: str, reason: str) -> Dict[str, Any]:
    return {
        "success": False,
        "tool": tool_name,
        "data": None,
        "error": {
            "code": LOOP_DETECTED,
            "message": reason,
            "details": {
                "rule": "no_progress",
                "guidance": "Change strategy: different tool, different "
                            "arguments, or finish with the result you have.",
            },
        },
        "retryable": False,
    }
