"""Runtime configuration + environment validation (agent_runtime_json v1.0).

Contracts (canonical copies in this package):
    contracts/agent_runtime_json/runtime.config.json
    contracts/agent_runtime_json/environment.template.json

runtime.config.json is the runtime DEFAULTS layer for the orchestrator:

    agent         : max_steps, max_retries_per_tool_call, max_identical_tool_calls,
                    task_timeout_ms, context_max_messages
    transports    : mcp {timeout_ms} | shell {timeout_ms, max_stdout_bytes,
                    max_stderr_bytes, shell:false}
    browser       : default_target, refresh_view_after_mutation,
                    reject_stale_element_index
    notifications : adapter (sse), persist_events
    logging       : redact_secrets, include_tool_arguments

Resolution order (highest wins):
    1. Settings (.env / deploy environment) — operator override
    2. runtime.config.json contract defaults (this file)

environment.template.json declares the variables the runtime REQUIRES and
their secret flag. ``validate_environment()`` verifies presence only — it
NEVER logs or returns values (contract rule: "redact from logs and events").
"""
from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

_CONTRACTS_DIR = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "contracts", "agent_runtime_json"
)


def load_contract(filename: str) -> Dict[str, Any]:
    """Load one contract JSON from contracts/agent_runtime_json/."""
    path = os.path.join(_CONTRACTS_DIR, filename)
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


# ── runtime.config.json ──────────────────────────────────────────────────────


@dataclass
class AgentLimits:
    max_steps: int = 20
    max_retries_per_tool_call: int = 2
    max_identical_tool_calls: int = 2
    task_timeout_ms: int = 900_000
    context_max_messages: int = 200


@dataclass
class TransportLimits:
    mcp_timeout_ms: int = 120_000
    shell_timeout_ms: int = 120_000
    shell_max_stdout_bytes: int = 1_000_000
    shell_max_stderr_bytes: int = 1_000_000
    shell_raw_allowed: bool = False  # contract: shell=false (never a raw shell)


@dataclass
class BrowserPolicy:
    default_target: str = "sandbox"
    refresh_view_after_mutation: bool = True
    reject_stale_element_index: bool = True


@dataclass
class NotificationPolicy:
    adapter: str = "sse"
    persist_events: bool = True


@dataclass
class LoggingPolicy:
    redact_secrets: bool = True
    include_tool_arguments: bool = False


@dataclass
class RuntimeConfig:
    agent: AgentLimits = field(default_factory=AgentLimits)
    transports: TransportLimits = field(default_factory=TransportLimits)
    browser: BrowserPolicy = field(default_factory=BrowserPolicy)
    notifications: NotificationPolicy = field(default_factory=NotificationPolicy)
    logging: LoggingPolicy = field(default_factory=LoggingPolicy)
    source: str = "contract+settings"


def _env_int(value: Any, default: int) -> int:
    try:
        parsed = int(str(value).strip())
        return parsed
    except (TypeError, ValueError):
        return default


@lru_cache(maxsize=1)
def get_runtime_config() -> RuntimeConfig:
    """Effective runtime config: contract defaults ← operator Settings.

    Settings wins where the deployment explicitly tunes a limit (e.g.
    MAX_STEPS=0 = unlimited steps by operator choice, or a longer shell
    timeout on a slow host). Values the Settings layer does not expose keep
    the contract defaults untouched.
    """
    contract = load_contract("runtime.config.json")

    agent = contract.get("agent") or {}
    transports = contract.get("transports") or {}
    mcp = transports.get("mcp") or {}
    shell = transports.get("shell") or {}
    browser = contract.get("browser") or {}
    notifications = contract.get("notifications") or {}
    logging_policy = contract.get("logging") or {}

    cfg = RuntimeConfig(
        agent=AgentLimits(
            max_steps=_env_int(agent.get("max_steps"), 20),
            max_retries_per_tool_call=_env_int(
                agent.get("max_retries_per_tool_call"), 2
            ),
            max_identical_tool_calls=_env_int(
                agent.get("max_identical_tool_calls"), 2
            ),
            task_timeout_ms=_env_int(agent.get("task_timeout_ms"), 900_000),
            context_max_messages=_env_int(
                agent.get("context_max_messages"), 200
            ),
        ),
        transports=TransportLimits(
            mcp_timeout_ms=_env_int(mcp.get("timeout_ms"), 120_000),
            shell_timeout_ms=_env_int(shell.get("timeout_ms"), 120_000),
            shell_max_stdout_bytes=_env_int(
                shell.get("max_stdout_bytes"), 1_000_000
            ),
            shell_max_stderr_bytes=_env_int(
                shell.get("max_stderr_bytes"), 1_000_000
            ),
            shell_raw_allowed=bool(shell.get("shell", False)),
        ),
        browser=BrowserPolicy(
            default_target=str(browser.get("default_target", "sandbox")),
            refresh_view_after_mutation=bool(
                browser.get("refresh_view_after_mutation", True)
            ),
            reject_stale_element_index=bool(
                browser.get("reject_stale_element_index", True)
            ),
        ),
        notifications=NotificationPolicy(
            adapter=str(notifications.get("adapter", "sse")),
            persist_events=bool(notifications.get("persist_events", True)),
        ),
        logging=LoggingPolicy(
            redact_secrets=bool(logging_policy.get("redact_secrets", True)),
            include_tool_arguments=bool(
                logging_policy.get("include_tool_arguments", False)
            ),
        ),
    )

    # ── Settings override layer (operator .env) ─────────────────────────
    try:
        from app.core.config import get_settings

        s = get_settings()
        # 0 = unlimited (operator choice, e.g. MAX_STEPS=0) — kept as 0.
        cfg.agent.max_steps = _env_int(
            getattr(s, "max_steps", None), cfg.agent.max_steps
        )
        cfg.agent.max_retries_per_tool_call = _env_int(
            getattr(s, "manus_max_retries_per_call", None),
            cfg.agent.max_retries_per_tool_call,
        )
        cfg.agent.max_identical_tool_calls = _env_int(
            getattr(s, "manus_max_identical_calls", None),
            cfg.agent.max_identical_tool_calls,
        )
        cfg.agent.task_timeout_ms = _env_int(
            getattr(s, "manus_task_timeout_ms", None), cfg.agent.task_timeout_ms
        )
        cfg.agent.context_max_messages = _env_int(
            getattr(s, "agent_context_max_messages", None),
            cfg.agent.context_max_messages,
        )
        cfg.transports.shell_timeout_ms = _env_int(
            getattr(s, "manus_shell_timeout_seconds", None),
            cfg.transports.shell_timeout_ms,
        ) * 1000  # settings unit = seconds, contract unit = ms
        cfg.transports.shell_max_stdout_bytes = _env_int(
            getattr(s, "manus_shell_max_output_chars", None),
            cfg.transports.shell_max_stdout_bytes,
        )
        cfg.source = "contract+settings"
    except Exception:  # noqa: BLE001 — settings unavailable → pure contract
        cfg.source = "contract"

    return cfg


# ── environment.template.json ────────────────────────────────────────────────

# Contract variable → the concrete env names this deployment accepts.
# Presence-only mapping; values are never read into logs.
_ENV_VAR_ALIASES: Dict[str, List[str]] = {
    "LLM_API_KEY": [
        "LLM_API_KEY",
        "NVIDIA_API_KEY",
        "NIM_API_KEY",
        "OPENAI_API_KEY",
        "OPENROUTER_API_KEY",
    ],
    "MCP_ENDPOINT": ["MCP_ENDPOINT", "MCP_CONFIG_PATH", "MCP_SERVERS_PATH"],
    "AGENT_DATABASE_URL": ["AGENT_DATABASE_URL", "MONGODB_URI", "DATABASE_URL"],
    "NOTIFICATION_PUBLIC_URL": ["NOTIFICATION_PUBLIC_URL", "PUBLIC_BASE_URL"],
}


def validate_environment() -> List[Dict[str, Any]]:
    """Verify required environment variables per environment.template.json.

    Returns a list of {name, required, secret, present} — booleans and names
    only, NEVER values. Logs a single summary line; missing REQUIRED vars are
    logged as WARNING so a broken deployment is visible at startup without
    crashing the process (the rest of the stack may still be useful).
    """
    try:
        template = load_contract("environment.template.json")
    except Exception:  # noqa: BLE001 — a missing contract must not kill startup
        logger.warning("environment.template.json unreadable — env check skipped")
        return []

    report: List[Dict[str, Any]] = []
    missing_required: List[str] = []
    for var in template.get("variables") or []:
        name = var.get("name")
        if not name:
            continue
        aliases = _ENV_VAR_ALIASES.get(name, [name])
        present = any(
            (os.environ.get(alias) or "").strip() for alias in aliases
        )
        report.append(
            {
                "name": name,
                "required": bool(var.get("required")),
                "secret": bool(var.get("secret")),
                "present": present,
            }
        )
        if var.get("required") and not present:
            missing_required.append(name)

    present_count = sum(1 for r in report if r["present"])
    logger.info(
        "Runtime environment check: %d/%d contract variables satisfied%s",
        present_count,
        len(report),
        "" if not missing_required
        else f" — MISSING REQUIRED: {missing_required}",
    )
    return report
