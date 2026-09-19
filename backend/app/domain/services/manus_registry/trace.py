"""Loop safety + structured trace for the Manus agent loop.

Per-task state:
  - trace entries: {step, tool, arguments_hash, success, state_changed,
    duration_ms, retry_count, error_code} — one per tool call, queryable
    for debugging.
  - identical-call detection: (tool, args_hash) repetition counting.
    WINDOW-BASED (not consecutive-only): interleaved filler calls (ls,
    browser_view) between failing retries no longer reset the streak —
    observed live (session 126051f9d15848b3): `npx tailwindcss init -p`
    failed 4x while `ls` probes in between kept "resetting" the old
    consecutive counter, so the model burned ~25 minutes looping.
  - command-family failure memory: for shell tools, failures are bucketed
    by the command's leading binary (npx X / ./node_modules/.bin/X /
    X --flag all collapse to family "X"). Once a family fails
    FAMILY_FAILURE_LIMIT times, ANY new call in that family is blocked
    with the last error excerpt attached — the model must pivot method,
    not polish flags (this is the Codex/Claude-Code behaviour: read the
    error, change approach, never blind-retry).
  - identical-error memory: the same (args, error) signature occurring
    IDENTICAL_ERROR_LIMIT times within the window blocks further calls
    with that signature. Successes no longer wipe the memory (windowing
    only) — an interleaved `ls` cannot launder a failing approach.
"""
from __future__ import annotations

import hashlib
import json
import logging
import time
from collections import Counter, deque
from typing import Any, Dict, List, Optional

from app.domain.services.manus_registry.errors import LOOP_DETECTED

logger = logging.getLogger(__name__)

IDENTICAL_CALL_LIMIT = 3
IDENTICAL_ERROR_LIMIT = 3
FAMILY_FAILURE_LIMIT = 3
_HISTORY_SIZE = 60
TRACE_MAX_ENTRIES = 500

# ── shell-command read-only classifier ─────────────────────────────────
# Binaries whose execution only READS state. Everything else (and any
# redirection / substitution anywhere in the command) is treated as
# mutating — conservative default, so the guard only ever UNDER-triggers.
_READONLY_SHELL_BINS = frozenset({
    "ls", "cat", "head", "tail", "grep", "rg", "find", "pwd", "echo",
    "which", "whoami", "id", "ps", "du", "df", "wc", "stat", "file",
    "env", "printenv", "date", "uname", "hostname", "free", "lscpu",
    "tree", "diff", "cmp", "md5sum", "sha256sum", "basename", "dirname",
    "realpath", "readlink", "test", "true", "false", "sleep", "sort",
    "uniq", "cut", "sed", "jq", "less", "more", "whereis", "locate",
    "groups", "tty", "printf",
})

# Subcommand-scoped read-only families: <bin> <read-only-sub> [...].
_READONLY_SHELL_SUBS: Dict[str, frozenset] = {
    "git": frozenset({"status", "log", "diff", "show", "branch", "remote",
                      "rev-parse", "describe", "ls-files", "config --get"}),
    "npm": frozenset({"list", "ls", "view", "outdated", "search", "ping",
                      "audit", "prefix", "root", "bin", "config get"}),
    "pip": frozenset({"list", "show", "check", "index", "cache list"}),
    "python": frozenset({"--version", "-V"}),
    "python3": frozenset({"--version", "-V"}),
    "node": frozenset({"--version", "-v"}),
    "yarn": frozenset({"list", "info", "outdated", "check", "versions"}),
}

# Multi-token read-only subcommands (checked against the joined tail).
_READONLY_MULTI = ("config --get", "cache list")

_REDIR_MARKERS = (">", ">>", "tee ", "| ")
# split chains so every segment must be read-only
_CHAIN_SPLIT = __import__("re").compile(r"(?:&&|\|\||;|\|)")


def _segment_read_only(segment: str) -> bool:
    seg = segment.strip().strip("(){}")
    if not seg:
        return True
    if any(m in seg for m in (">", "tee ")):
        return False
    if seg.startswith("cd ") or seg == "cd":
        return True  # cd only moves the cursor, changes nothing on disk
    tokens = seg.split()
    if not tokens:
        return True
    binary = tokens[0].rsplit("/", 1)[-1]
    subs = _READONLY_SHELL_SUBS.get(binary)
    if subs is not None:
        rest = " ".join(tokens[1:])
        if rest.startswith(tuple(subs)) or any(rest.startswith(m) for m in _READONLY_MULTI):
            return True
        return False
    if binary.startswith("-"):
        # option-looking token first (rare) — treat as mutating
        return False
    return binary in _READONLY_SHELL_BINS


def shell_command_read_only(command: str) -> bool:
    """True only when EVERY chain segment is a known read-only operation."""
    if not command:
        return False
    for segment in _CHAIN_SPLIT.split(command):
        if not _segment_read_only(segment):
            return False
    return True


# Tools that CHANGE state when executed (anything not listed here and not
# shell-classified is treated as mutating — conservative default).
_READONLY_TOOLS = frozenset({
    "file_read", "file_list_dir", "file_search", "file_glob", "file_grep",
    "browser_view", "browser_console_view", "browser_list_tabs",
    "browser_find_keyword", "browser_get_select_options",
    "browser_verify_value", "browser_wait_for_element",
    "browser_wait_for_network_idle", "shell_view", "shell_wait",
    "info_search", "info_search_web", "info_search_image", "info_locate",
    "message_notify_user",
})


def _is_mutating(tool_name: str, arguments: Dict[str, Any]) -> bool:
    """Whether executing this call plausibly changes the world.

    Drives the mutation-aware walk-backs: a retry AFTER a mutating action
    is an informed attempt (the model changed something on purpose), while
    a retry interleaved only by read-only probes is a blind one."""
    if tool_name in _READONLY_TOOLS:
        return False
    if tool_name.startswith(("shell_", "manus-")):
        raw = str(arguments.get("command") or arguments.get("cmd") or "")
        return not shell_command_read_only(raw)
    return True


def _command_family(tool_name: str, arguments: Dict[str, Any]) -> str:
    """Leading-binary family key for shell-transport calls, else "".

    Reuses the loop_detector's leading_binary normalisation so the hard
    gate and the soft nudges speak the same language:
      'cd /x && npx tailwindcss init'  -> 'tailwindcss'
      './node_modules/.bin/tailwindcss -i a.css' -> 'tailwindcss'
    """
    if not tool_name.startswith(("shell_", "manus-")):
        return ""
    try:
        from app.domain.services.agents.loop_detector import leading_binary

        raw = str(
            arguments.get("command")
            or arguments.get("cmd")
            or ""
        )
        return leading_binary(raw)
    except Exception:  # noqa: BLE001 — guard must never break dispatch
        return ""


# Pure observation / waiting / communication tools: legitimately repeat
# (wait → view polling while a process boots, fresh browser snapshots while
# an animation settles). The HARD rules never block them — the soft
# ActionLoopDetector still nudges if even these start repeating.
_HARD_EXEMPT_TOOLS = frozenset({
    "browser_view", "browser_console_view", "browser_list_tabs",
    "browser_wait_for_element", "browser_wait_for_network_idle",
    "browser_get_select_options", "browser_verify_value",
    "message_notify_user", "message_ask_user",
    "shell_view", "shell_wait",
})


def failure_loop_payload(
    tool_name: str,
    reason: str,
    last_error: str = "",
    family: Optional[str] = None,
    rule: str = "no_progress",
) -> Dict[str, Any]:
    """Structured LOOP_DETECTED failure — carries the actual error excerpt
    and a concrete pivot checklist so the model can DIAGNOSE instead of
    guessing its way around the block."""
    excerpt = " ".join(str(last_error or "").split())[:280]
    guidance_lines = [
        "1. READ the last error below and state (one line) what actually went wrong.",
        "2. Run ONE inspection command that tests your hypothesis "
        "(check installed versions, read the log file, list what exists).",
        "3. Then use a FUNDAMENTALLY different method — different tool, "
        "different library/approach, or finish with the data you already have.",
        "Do NOT retry this call or near-variants of it: identical and "
        "family-identical calls are now BLOCKED by the loop guard.",
    ]
    details: Dict[str, Any] = {
        "rule": rule,
        "guidance": " ".join(guidance_lines),
    }
    if excerpt:
        details["last_error"] = excerpt
    if family:
        details["command_family"] = family
    return {
        "success": False,
        "tool": tool_name,
        "data": None,
        "error": {
            "code": LOOP_DETECTED,
            "message": reason,
            "details": details,
        },
        "retryable": False,
    }


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
    """Detects non-progress tool-call patterns within one agent run.

    Codex/Claude-Code-style harness discipline: the harness — not the
    model's self-control — decides when a pattern is non-progress, and
    HARD-BLOCKS the call with a diagnostic payload.

    Two rules, both checked before execution; both are MUTATION-AWARE
    (a real change to the world between attempts legitimises a retry —
    build → fix file → build again is normal engineering, while
    build → ls → build → cat → build is a blind retry spiral):

      1. BLIND REPEAT — the same (tool, args_hash) executed
        ``identical_call_limit`` times with the SAME outcome signature and
        no mutating action in between: the world was not changed, the
        output will not change either. Interleaved ls/cat probes no longer
        reset the count (the consecutive-only guard missed exactly this on
        session 126051f9d15848b3: `npx tailwindcss init -p` failed 4x).
      2. FAMILY FAILURES — for shell commands, failures are bucketed by
        the command's leading binary (npx X / ./node_modules/.bin/X /
        X --flag all collapse to family "X"). After
        ``family_failure_limit`` failures with no mutating action or
        family success in between, ANY new call in that family is blocked
        with the last error excerpt attached — the model must pivot
        method, not polish flags.

    Block payloads carry: what to read, the last error excerpt, and a
    concrete pivot checklist (see failure_loop_payload).
    """

    def __init__(self) -> None:
        # Limits are contract-configurable (agent-orchestrator contract:
        # max_identical_calls=2); settings win, module constants are the
        # fallback when the settings layer is unavailable (unit tests).
        try:
            from app.core.config import get_settings
            _s = get_settings()
            self.identical_call_limit = max(
                2, int(getattr(_s, "manus_max_identical_calls", IDENTICAL_CALL_LIMIT))
            )
            self.identical_error_limit = max(
                2, int(getattr(_s, "manus_max_identical_errors", IDENTICAL_ERROR_LIMIT))
            )
            self.family_failure_limit = max(
                2, int(getattr(_s, "manus_family_failure_limit", FAMILY_FAILURE_LIMIT))
            )
        except Exception:  # noqa: BLE001 — tests / early startup
            self.identical_call_limit = IDENTICAL_CALL_LIMIT
            self.identical_error_limit = IDENTICAL_ERROR_LIMIT
            self.family_failure_limit = FAMILY_FAILURE_LIMIT
        # Rolling history of executed calls: {hash, outcome, family, mutating}.
        # Walked BACKWARD by both rules; bounded so memory stays flat.
        self._history: deque = deque(maxlen=_HISTORY_SIZE)
        # Diagnostic excerpts per args_hash / family for block messages.
        self._hash_last_outcome: Dict[str, str] = {}
        self._family_last_error: Dict[str, str] = {}
        self.blocked_message: Optional[str] = None

    # ── pre-execution check ───────────────────────────────────────────

    def check_before_execute(
        self,
        tool_name: str,
        args_hash: str,
        arguments: Optional[Dict[str, Any]] = None,
    ) -> Optional[Dict[str, Any]]:
        """Return a LOOP_DETECTED failure payload when this call is a known
        non-progress pattern."""
        if tool_name in _HARD_EXEMPT_TOOLS:
            return None
        # 1) blind repeat: same call + same outcome + no mutation between
        repeats, outcome_sig = self._blind_repeat_count(args_hash)
        if repeats >= self.identical_call_limit:
            excerpt = self._hash_last_outcome.get(args_hash, "")
            self.blocked_message = (
                f"Identical call already ran {repeats}x with the SAME result "
                f"and nothing changed in between (hash {args_hash})."
            )
            return failure_loop_payload(
                tool_name,
                self.blocked_message,
                last_error=excerpt,
                rule="blind_repeat",
            )

        # 2) command-family failures (shell commands with a command string)
        family = _command_family(tool_name, arguments or {})
        if family:
            fam_fails = self._family_failures_since_progress(family)
            if fam_fails >= self.family_failure_limit:
                self.blocked_message = (
                    f"Command family '{family}' already failed {fam_fails}x "
                    f"in this task without any state change in between. The "
                    f"APPROACH is failing in this environment — flag/path/"
                    f"spelling variants will not fix it."
                )
                return failure_loop_payload(
                    tool_name,
                    self.blocked_message,
                    last_error=self._family_last_error.get(family, ""),
                    family=family,
                    rule="family_failure",
                )
        return None

    # ── outcome recording ─────────────────────────────────────────────

    def record_result(
        self,
        tool_name: str,
        args_hash: str,
        success: bool,
        error_code: str = "",
        error_message: str = "",
        output_excerpt: str = "",
        arguments: Optional[Dict[str, Any]] = None,
    ) -> Optional[Dict[str, Any]]:
        """Record one executed outcome into the window.

        On repeated identical failures returns a stop payload so callers can
        short-circuit; on success it is just bookkeeping (family recovery is
        derived from the history walk, nothing to clear here)."""
        excerpt = " ".join(str(error_message or output_excerpt or "").split())[:300]
        outcome_sig = hashlib.sha256(
            f"{1 if success else 0}|{error_code}|{excerpt}".encode()
        ).hexdigest()[:12]
        family = _command_family(tool_name, arguments or {})
        self._history.append({
            "hash": args_hash,
            "outcome": outcome_sig,
            "family": family,
            "mutating": _is_mutating(tool_name, arguments or {}),
            "success": success,
        })
        self._hash_last_outcome[args_hash] = (
            ("ERROR: " + excerpt) if (excerpt and not success) else excerpt
        )
        if family and not success:
            self._family_last_error[family] = excerpt
        # immediate stop on the same (call, error) recurring within the
        # history window even when interleaved by read-only probes
        if not success:
            fails = 0
            for entry in reversed(self._history):
                if entry["hash"] == args_hash:
                    if entry["outcome"] == outcome_sig:
                        fails += 1
                        if fails >= self.identical_error_limit:
                            return failure_loop_payload(
                                tool_name,
                                f"The same call failed with the same error "
                                f"{fails}x without progress "
                                f"({error_code}: {excerpt[:160]}).",
                                last_error=excerpt,
                                family=family or None,
                                rule="error_memory",
                            )
                    else:
                        break  # outcome changed → progress was made
                elif entry["mutating"]:
                    break
        return None

    def record_error(
        self,
        tool_name: str,
        error_code: str,
        message: str,
        args_hash: str = "",
        arguments: Optional[Dict[str, Any]] = None,
    ) -> Optional[Dict[str, Any]]:
        """Backward-compatible wrapper kept for existing gate callers."""
        return self.record_result(
            tool_name,
            args_hash,
            success=False,
            error_code=error_code,
            error_message=message,
            arguments=arguments,
        )

    def record_success(self, *args, **kwargs) -> None:
        """Backward-compatible no-op: recovery is derived from the history
        walk (a family success or an intervening mutation), so there is
        nothing to 'wipe' — an interleaved `ls` can no longer launder a
        failing approach (the exact bug on session 126051f9d15848b3)."""
        return None

    # ── history walks ─────────────────────────────────────────────────

    def _blind_repeat_count(self, args_hash: str) -> tuple:
        """(count, outcome_sig) of consecutive-backward occurrences of this
        exact call with identical outcomes and no mutating call in between."""
        count = 0
        outcome_sig = None
        for entry in reversed(self._history):
            if entry["hash"] == args_hash:
                if outcome_sig is None:
                    outcome_sig = entry["outcome"]
                    count = 1
                elif entry["outcome"] == outcome_sig:
                    count += 1
                else:
                    break  # outcome changed between attempts → progress
                if count >= self.identical_call_limit:
                    break
            elif entry["mutating"]:
                break  # the world changed since the last attempt → fresh try
        return count, outcome_sig

    def _family_failures_since_progress(self, family: str) -> int:
        """Failures of this command family since the last family success or
        the last mutating action (whichever is more recent)."""
        count = 0
        for entry in reversed(self._history):
            if entry["family"] == family:
                if entry["success"]:
                    break  # family recovered → fresh budget
                count += 1
                if count >= self.family_failure_limit:
                    break
            elif entry["mutating"]:
                break  # a state change happened → the retry is informed
        return count
