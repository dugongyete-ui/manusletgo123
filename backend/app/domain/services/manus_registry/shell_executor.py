"""Shell transport executor for the Manus registry (16 manus-* CLI tools).

Security contract (hard requirements from the Manus standard):

1. ALLOWLIST — only the 16 registry-declared manus-* executables may run;
   the allowlist is derived from registry.json, never hard-coded here.
2. ABSOLUTE PATH — every executable resolves to a fixed absolute path under
   MANUS_TOOLS_BIN_DIR.
3. NO RAW SHELL — the model supplies ``{executable, argv:[str]}``; the
   executor builds the command line itself with shlex.quote() per element.
   A model-supplied command STRING is rejected outright.
4. NO shell escapes — argv elements matching bash/sh/-c/eval/--command (or
   containing NUL / newlines / shell metacharacters after quoting) are
   rejected by schema pattern + explicit deny-list.
5. TIMEOUT — executor wraps the call in coreutils `timeout <seconds>`.
6. BOUNDED WORKING DIR — commands run with exec_dir pinned to the sandbox
   user home (never the app source).
7. BOUNDED OUTPUT — stdout/stderr truncated to MANUS_SHELL_MAX_OUTPUT_CHARS.
8. EXIT CODE — captured and returned in the payload.
9. SECRET REDACTION — output passes redact_secrets() before it reaches the
   model, the UI, or the logs.

Note on transport: the platform sandbox exposes `exec_command(command)`
over HTTP; the equivalent of subprocess shell=False is achieved by
construction — the model can never emit a shell string because every argv
token is quoted as a literal by the executor.
"""
from __future__ import annotations

import logging
import shlex
from typing import Any, Dict, List, Optional, Tuple

from app.core.config import get_settings
from app.domain.external.sandbox import Sandbox
from app.domain.models.tool_result import ToolResult
from app.domain.services.manus_registry.errors import (
    EXECUTION_ERROR,
    NOT_SUPPORTED,
    PERMISSION_DENIED,
    TIMEOUT,
    VALIDATION_ERROR,
    failure_payload,
    redact_secrets,
    success_payload,
)
from app.domain.services.manus_registry.loader import get_tool_def, list_tools
from app.domain.services.manus_registry.security_policy import (
    argv_reject_reason,
    shell_allowlist_check,
)

logger = logging.getLogger(__name__)

# Deny-list on top of the schema pattern (defense in depth). The CONTRACT
# tokens (security.policy.json shell.reject_args) are merged with the
# deployment's extended deny-list — the union is always enforced.
from app.domain.services.manus_registry.security_policy import CONTRACT_REJECT_ARGS as _CONTRACT_REJECT
_DENY_EXACT = set(_CONTRACT_REJECT) | {
    "bash", "sh", "-c", "--command", "eval", "exec", "env", "sudo",
    "rm", "mkfs", "dd", "chmod", "chown",
}
_DENY_SUBSTR = ("\x00", "\n", "\r", "`", "$(", "${", "&&", "||", ";", "|", "&")


def shell_allowlist() -> List[str]:
    """The 16 available manus-* executables, derived from the registry."""
    return [
        t["name"]
        for t in list_tools(transport="shell", enabled_only=True)
    ]


def unavailable_shell_tools() -> List[str]:
    """Registry shell tools documented as unavailable (marked disabled)."""
    out = []
    for t in get_tool_def_all_shell():
        notes = " ".join(t.get("notes") or []).lower()
        if "unavailable" in notes:
            out.append(t["name"])
    return out


def get_tool_def_all_shell():
    from app.domain.services.manus_registry.loader import get_registry
    return [t for t in get_registry()["tools"] if t["transport"] == "shell"]


def _validate_argv(argv: List[str]) -> Tuple[bool, str]:
    """Hard argv validation beyond the JSON schema pattern."""
    if not isinstance(argv, list):
        return False, "argv must be an array of strings"
    if len(argv) > 32:
        return False, "argv exceeds the maximum of 32 items"
    for i, item in enumerate(argv):
        if not isinstance(item, str):
            return False, f"argv[{i}] must be a string"
        if item.lower() in _DENY_EXACT:
            return False, f"argv[{i}] '{item}' is a forbidden shell token"
        for bad in _DENY_SUBSTR:
            if bad in item:
                return False, (
                    f"argv[{i}] contains forbidden sequence {bad!r} — "
                    "argv must be plain literal tokens, never shell syntax"
                )
        if len(item) > 1024:
            return False, f"argv[{i}] exceeds 1024 characters"
    return True, ""


class ManusShellExecutor:
    """Executes the 16 allowlisted manus-* CLI tools inside the sandbox."""

    def __init__(self, sandbox: Sandbox) -> None:
        self._sandbox = sandbox

    @property
    def _bin_dir(self) -> str:
        """Resolved manus-tools directory.

        Environment-adaptive (Replit / z.ai / VPS): explicit env override
        wins, otherwise the directory is auto-resolved OUTSIDE the sandbox
        protected paths and auto-deployed from the repo's canonical copy on
        first use — no hardcoded host path, no manual build step.
        """
        settings = get_settings()
        explicit = (getattr(settings, "manus_tools_bin_dir", "") or "").strip()
        if explicit:
            from app.domain.services.manus_registry.deploy import (
                ensure_manus_tools_deployed,
            )
            return ensure_manus_tools_deployed(explicit)
        from app.domain.services.manus_registry.deploy import get_manus_tools_bin_dir
        return get_manus_tools_bin_dir()

    @property
    def _timeout(self) -> int:
        return get_settings().manus_shell_timeout_seconds

    @property
    def _max_output(self) -> int:
        return get_settings().manus_shell_max_output_chars

    async def execute(
        self,
        tool_name: str,
        arguments: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Run one shell-transport tool. Returns the normalized payload."""
        # 1) registry lookup + availability
        tool_def = get_tool_def(tool_name)
        if not tool_def or tool_def.get("transport") != "shell":
            return failure_payload(
                tool_name, VALIDATION_ERROR,
                f"'{tool_name}' is not a registered shell tool.",
            )
        notes = " ".join(tool_def.get("notes") or []).lower()
        if tool_def.get("enabled") is False or "unavailable" in notes:
            return failure_payload(
                tool_name, NOT_SUPPORTED,
                f"'{tool_name}' is documented unavailable in this "
                "environment (see registry notes).",
            )

        # 2) arguments shape: {executable, argv} — never a raw command string
        executable = arguments.get("executable")
        argv = arguments.get("argv")
        if "command" in arguments and not isinstance(arguments.get("argv"), list):
            return failure_payload(
                tool_name, VALIDATION_ERROR,
                "Raw command strings are forbidden. Provide "
                "{executable, argv:[... literal tokens ...]} instead.",
            )
        if executable != tool_name:
            return failure_payload(
                tool_name, VALIDATION_ERROR,
                f"executable must be '{tool_name}' (registry const), "
                f"got {executable!r}",
            )
        # 2b) contract security.policy.json: shell.reject_args scan FIRST —
        #     bash/sh/-c/--command/eval as argv tokens are denied outright
        #     (raw shell invocation is forbidden, allow_raw_shell_command=false).
        #     The contract layer runs before the schema-shape validation so a
        #     token that slips both schemas still dies here with PERMISSION_DENIED.
        contract_reason = argv_reject_reason(argv or [])
        if contract_reason:
            return failure_payload(tool_name, PERMISSION_DENIED, contract_reason)

        ok, reason = _validate_argv(argv or [])
        if not ok:
            return failure_payload(tool_name, VALIDATION_ERROR, reason)

        # 3) allowlist + absolute path — the registry-derived allowlist AND
        #    the contract /usr/local/bin/manus-* basenames are BOTH enforced.
        allow = shell_allowlist()
        if tool_name not in allow:
            return failure_payload(
                tool_name, VALIDATION_ERROR,
                f"'{tool_name}' is not on the shell allowlist {allow}",
            )
        contract_ok, contract_denial = shell_allowlist_check(tool_name)
        if not contract_ok:
            return failure_payload(tool_name, PERMISSION_DENIED, contract_denial)
        bin_path = f"{self._bin_dir}/{tool_name}"

        # 4) executor-built command line: absolute allowlisted path +
        #    per-token quoting (shell=False equivalent) + coreutils timeout
        quoted = " ".join(shlex.quote(tok) for tok in argv)
        command = f"timeout {int(self._timeout)} {shlex.quote(bin_path)} {quoted}".strip()

        # 5) run inside the sandbox (bounded cwd = user home via exec_dir="")
        import uuid as _uuid
        try:
            tr: ToolResult = await self._sandbox.exec_command(
                str(_uuid.uuid4()), "", command
            )
        except Exception as exc:  # noqa: BLE001
            from app.domain.services.manus_registry.errors import classify_exception
            return failure_payload(tool_name, classify_exception(exc), str(exc))

        stdout = str((tr.data or {}).get("output", "") or "") if isinstance(tr.data, dict) else (tr.message or "")
        stderr = str((tr.data or {}).get("stderr", "") or "") if isinstance(tr.data, dict) else ""

        exit_code = self._extract_exit_code(tr)
        timed_out = "timed out" in stdout.lower() or exit_code == 124

        # The CLI prints a structured JSON verdict — it is the ground truth
        # for success/failure (the sandbox transport only reports transport
        # success, and the CLI distinguishes handled errors from crashes via
        # exit codes 0 / 2).
        parsed = self._parse_cli_json(stdout)

        payload: Dict[str, Any] = {
            "executable": bin_path,
            "argv": redact_secrets(argv or []),
            "exit_code": exit_code,
            "stdout": redact_secrets(stdout[: self._max_output]),
            "stderr": redact_secrets(stderr[: self._max_output // 2]),
            "duration_capped_seconds": self._timeout,
        }
        if timed_out:
            return failure_payload(
                tool_name, TIMEOUT,
                f"Shell tool exceeded {self._timeout}s and was terminated.",
                payload,
            )
        if parsed is not None and parsed.get("ok") is False:
            err = parsed.get("error") or {}
            payload["cli_error_code"] = err.get("code")
            if isinstance(parsed.get("error"), dict):
                payload["details"] = redact_secrets({
                    k: v for k, v in parsed["error"].items()
                    if k not in ("code", "message")
                })
            return failure_payload(
                tool_name,
                err.get("code") or EXECUTION_ERROR,
                err.get("message") or f"exit code {exit_code}",
                payload,
            )
        if parsed is not None and parsed.get("ok") is True:
            payload["result"] = redact_secrets(parsed.get("data") or {})
        if not parsed and exit_code != 0:
            return failure_payload(
                tool_name, EXECUTION_ERROR,
                stdout[:500] or f"exit code {exit_code}",
                payload,
            )
        return success_payload(tool_name, payload)

    @staticmethod
    def _parse_cli_json(stdout: str) -> Optional[Dict[str, Any]]:
        """Extract the first JSON object line from CLI output."""
        import json as _json
        for line in stdout.splitlines():
            line = line.strip()
            if line.startswith('{"ok"'):
                try:
                    return _json.loads(line)
                except Exception:
                    return None
        return None

    @staticmethod
    def _extract_exit_code(tr: ToolResult) -> int:
        if isinstance(tr.data, dict):
            rc = tr.data.get("returncode")
            if rc is not None:
                try:
                    return int(rc)
                except Exception:
                    pass
        return 0
