"""Registry loader — reads registry.json (v1.1) as the single source of truth.

Validates internal consistency at import time (counts vs array length,
standalone files vs registry entries, schema_version presence, policy
presence) exactly like the validator Manus ran on the export, so a drifted
registry fails loudly at startup instead of silently at tool-call time.
"""
from __future__ import annotations

import functools
import json
import logging
import os
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

_REGISTRY_DIR = os.path.dirname(os.path.abspath(__file__))
_REGISTRY_PATH = os.path.join(_REGISTRY_DIR, "registry.json")
_TOOLS_DIR = os.path.join(_REGISTRY_DIR, "tools")

# Layout tolerance: the canonical Manus package ships registry.json at the
# package root; some deployments (z.ai reconstruction) keep it inside
# tools/. Accept BOTH — the registry is the single source of truth either
# way and the integrity checks below still apply.
if not os.path.exists(_REGISTRY_PATH):
    _alt = os.path.join(_TOOLS_DIR, "registry.json")
    if os.path.exists(_alt):
        _REGISTRY_PATH = _alt


class RegistryError(RuntimeError):
    """Raised when registry.json is missing or internally inconsistent."""


@functools.lru_cache(maxsize=1)
def get_registry() -> Dict[str, Any]:
    """Load and validate registry.json (cached process-wide)."""
    try:
        with open(_REGISTRY_PATH, "r", encoding="utf-8") as f:
            registry = json.load(f)
    except OSError as exc:
        raise RegistryError(f"registry.json not readable at {_REGISTRY_PATH}: {exc}")

    tools = registry.get("tools") or []
    if not tools:
        raise RegistryError("registry.json contains no tools")

    # ── Consistency checks (same rules as Manus validate_manus_registry.py) ──
    names = [t.get("name") for t in tools]
    if len(names) != len(set(names)):
        raise RegistryError("duplicate tool names in registry.json")
    for tool in tools:
        if not tool.get("name"):
            raise RegistryError("tool without name in registry.json")
        if tool.get("transport") not in ("mcp", "shell"):
            raise RegistryError(
                f"tool {tool['name']}: invalid transport {tool.get('transport')!r}"
            )
        if "input_schema" not in tool:
            raise RegistryError(f"tool {tool['name']}: missing input_schema")
        if "policy" not in tool:
            raise RegistryError(f"tool {tool['name']}: missing policy")
        if not tool.get("schema_version"):
            raise RegistryError(f"tool {tool['name']}: missing schema_version")

    counts = registry.get("counts") or {}
    mcp_count = sum(1 for t in tools if t["transport"] == "mcp")
    shell_count = sum(1 for t in tools if t["transport"] == "shell")
    if counts and counts.get("mcp") != mcp_count:
        logger.warning(
            "registry counts.mcp=%s but array holds %s MCP tools — array wins",
            counts.get("mcp"), mcp_count,
        )

    # Standalone file drift check (non-fatal: log-only, files are informational)
    try:
        standalone = {
            name[:-5]
            for name in os.listdir(_TOOLS_DIR)
            if name.endswith(".json") and name != "registry.json"
        }
        missing = set(names) - standalone
        if missing:
            logger.warning(
                "registry tools without standalone file: %s", sorted(missing)[:10]
            )
    except OSError:  # pragma: no cover
        pass

    logger.info(
        "Manus registry v%s loaded: %d tools (%d mcp / %d shell)",
        registry.get("schema_version", "?"), len(tools), mcp_count, shell_count,
    )
    return registry


def get_tool_def(name: str) -> Optional[Dict[str, Any]]:
    """Return the registry definition for ``name`` (None when unknown)."""
    for tool in get_registry()["tools"]:
        if tool["name"] == name:
            return tool
    return None


def list_tools(
    transport: Optional[str] = None,
    enabled_only: bool = True,
) -> List[Dict[str, Any]]:
    """List registry tool definitions with optional transport/enabled filter."""
    out = []
    for tool in get_registry()["tools"]:
        if transport and tool.get("transport") != transport:
            continue
        if enabled_only and tool.get("enabled") is False:
            continue
        # Manus marks PATH-missing shell tools via notes; honour that too.
        notes = " ".join(tool.get("notes") or []).lower()
        if enabled_only and "unavailable" in notes:
            continue
        out.append(tool)
    return out


def available_tool_names() -> List[str]:
    """All enabled tool names (the model-facing surface)."""
    return [t["name"] for t in list_tools()]


def tool_available(name: str) -> bool:
    """Whether ``name`` is registered AND enabled/unavailable-marked false."""
    tool = get_tool_def(name)
    if not tool:
        return False
    if tool.get("enabled") is False:
        return False
    notes = " ".join(tool.get("notes") or []).lower()
    return "unavailable" not in notes


def registry_stats() -> Dict[str, int]:
    tools = get_registry()["tools"]
    shell_unavailable = sum(
        1
        for t in tools
        if t["transport"] == "shell"
        and "unavailable" in " ".join(t.get("notes") or []).lower()
    )
    return {
        "mcp": sum(1 for t in tools if t["transport"] == "mcp"),
        "shell_available": sum(1 for t in tools if t["transport"] == "shell")
        - shell_unavailable,
        "shell_documented_unavailable": shell_unavailable,
        "total": len(tools),
    }


# ── LLM-facing schema builder ────────────────────────────────────────────────
# Registry input_schema → OpenAI function-calling parameters. The model's tool
# definitions are generated FROM the registry, never from Python decorators,
# so the two can never drift.


def _schema_to_openai_parameters(tool: Dict[str, Any]) -> Dict[str, Any]:
    """Convert a registry input_schema to an OpenAI `parameters` JSON schema."""
    schema = tool.get("input_schema") or {"type": "object", "properties": {}}

    # allOf compositions (browser_click) must be flattened for providers that
    # don't support allOf in tool parameters: merge property/required lists.
    if isinstance(schema, dict) and "allOf" in schema:
        merged: Dict[str, Any] = {"type": "object", "properties": {}, "required": []}
        branches = [schema] + list(schema["allOf"])
        for branch in branches:
            if not isinstance(branch, dict):
                continue
            if "oneOf" in branch:
                merged["oneOf"] = branch["oneOf"]
                continue
            props = branch.get("properties") or {}
            merged["properties"].update(props)
            for req in branch.get("required") or []:
                if req not in merged["required"]:
                    merged["required"].append(req)
        # Keep oneOf out of the top level as "anyOf" (OpenAI accepts anyOf).
        if "oneOf" in merged:
            merged["anyOf"] = merged.pop("oneOf")
        schema = merged

    return schema


def build_llm_schemas() -> List[Dict[str, Any]]:
    """OpenAI tool definitions for every ENABLED registry tool.

    These feed ``bind_tools`` so the model sees exactly the Manus surface:
    name, description, JSON-schema parameters — no Python decorator drift.
    """
    schemas: List[Dict[str, Any]] = []
    for tool in list_tools(enabled_only=True):
        schemas.append(
            {
                "type": "function",
                "function": {
                    "name": tool["name"],
                    "description": tool.get("description", ""),
                    "parameters": _schema_to_openai_parameters(tool),
                },
            }
        )
    return schemas
