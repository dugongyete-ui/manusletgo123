"""Security policy (agent_runtime_json v1.0 — security.policy.json).

Contract layer on top of the registry gate + shell executor:

defaults.allow_unknown_tools        = false → unknown registry names never
                                              execute (platform-native tools
                                              are a documented, separate
                                              surface — not "unknown")
defaults.allow_disabled_tools       = false → enabled:false / notes:"unavailable"
                                              tools are rejected
defaults.allow_raw_shell_command    = false → the model can only send
                                              {executable, argv:[literal]}
defaults.log_secrets                = false → redact_secrets() everywhere
defaults.send_secrets_to_model      = false → secret values never enter
                                              payloads returned to the model

confirmation_required_for: the impact categories that MUST pause for user
approval — destructive, database_changes, secret_changes,
external_submission, billing, permission_changes, delete_operations.
Registry tools map to these via their policy flags (policy.side_effects /
policy.destructive / policy.requires_confirmation).

shell.allowlist: contract lists the deployed /usr/local/bin/manus-* binaries.
This deployment resolves the manus-tools directory dynamically
(MANUS_TOOLS_BIN_DIR / deploy.py), so the allowlist is enforced on the
EXECUTABLE BASENAME — the invariant the contract actually pins.

shell.reject_args: argv tokens that immediately deny a call (bash, sh, -c,
--command, eval).
"""
from __future__ import annotations

import logging
from typing import Any, Dict, FrozenSet, List, Optional, Tuple

from app.domain.services.manus_registry.runtime_config import load_contract

logger = logging.getLogger(__name__)


def _load_policy() -> Dict[str, Any]:
    try:
        return load_contract("security.policy.json")
    except Exception:  # noqa: BLE001 — missing contract → fail-CLOSED defaults
        logger.warning(
            "security.policy.json unreadable — using fail-closed defaults"
        )
        return {}


_CONTRACT = _load_policy()

# ── defaults ─────────────────────────────────────────────────────────────────
_DEFAULTS: Dict[str, bool] = {
    "allow_unknown_tools": False,
    "allow_disabled_tools": False,
    "allow_raw_shell_command": False,
    "log_secrets": False,
    "send_secrets_to_model": False,
}
for key, value in (_CONTRACT.get("defaults") or {}).items():
    if key in _DEFAULTS and isinstance(value, bool):
        _DEFAULTS[key] = value

# ── confirmation categories ──────────────────────────────────────────────────
CONFIRMATION_CATEGORIES: Tuple[str, ...] = tuple(
    _CONTRACT.get("confirmation_required_for")
    or (
        "destructive",
        "database_changes",
        "secret_changes",
        "external_submission",
        "billing",
        "permission_changes",
        "delete_operations",
    )
)

# ── shell allowlist / reject args ────────────────────────────────────────────
_CONTRACT_SHELL_ALLOWLIST: FrozenSet[str] = frozenset(
    _CONTRACT.get("shell", {}).get("allowlist") or []
)

CONTRACT_REJECT_ARGS: FrozenSet[str] = frozenset(
    _CONTRACT.get("shell", {}).get("reject_args")
    or ("bash", "sh", "-c", "--command", "eval")
)


def policy_defaults() -> Dict[str, bool]:
    """Effective security defaults (contract JSON, fail-closed fallback)."""
    return dict(_DEFAULTS)


def contract_shell_allowlist_basenames() -> FrozenSet[str]:
    """Executable BASENAMES the contract allowlist pins (/usr/local/bin/manus-*)."""
    return frozenset(
        path.rsplit("/", 1)[-1] for path in _CONTRACT_SHELL_ALLOWLIST if path
    )


def shell_allowlist_check(executable_basename: str) -> Tuple[bool, str]:
    """Contract allowlist check for one shell executable basename.

    The contract list and the registry-declared manus-* tools are UNIONED:
    a binary is runnable when EITHER source pins it, so deployments that
    ship extra registry tools are not bricked while unknown binaries stay
    rejected (allow_unknown_tools=false).
    """
    if not executable_basename:
        return False, "empty executable"
    if executable_basename in contract_shell_allowlist_basenames():
        return True, ""
    # Registry-derived supplement (single source of truth for this install).
    try:
        from app.domain.services.manus_registry.loader import list_tools

        registry_shell = {
            t["name"] for t in list_tools(transport="shell", enabled_only=False)
        }
        if executable_basename in registry_shell:
            return True, ""
    except Exception:  # noqa: BLE001 — registry unavailable → contract only
        pass
    return False, (
        f"executable '{executable_basename}' is not on the shell allowlist "
        "(security.policy.json)"
    )


def argv_reject_reason(argv: Optional[List[str]]) -> Optional[str]:
    """Contract reject_args scan — returns the denial reason or None."""
    if not argv:
        return None
    for i, token in enumerate(argv):
        if not isinstance(token, str):
            continue
        if token.lower() in CONTRACT_REJECT_ARGS:
            return (
                f"argv[{i}] '{token}' matches security.policy.json "
                "shell.reject_args — raw shell invocation is forbidden"
            )
    return None


def confirmation_category(tool_def: Dict[str, Any]) -> Optional[str]:
    """Map a registry tool's policy flags to a confirmation category.

    Returns the FIRST matching contract category, or None when the tool is
    reversible/ordinary per the registry policy.
    """
    policy = tool_def.get("policy") or {}
    if not policy:
        return None
    side_effects = str(policy.get("side_effects") or "").lower()
    destructive = bool(policy.get("destructive"))
    requires = bool(policy.get("requires_confirmation"))

    if not (destructive or requires or side_effects):
        return None

    # Direct keyword hits on the declared side-effects string.
    for category in CONFIRMATION_CATEGORIES:
        if category in side_effects:
            return category
    if destructive:
        return "destructive"
    if requires:
        # Registry explicitly requires confirmation but no finer category —
        # report the generic consequence bucket.
        return "destructive" if destructive else "permission_changes"
    return None
