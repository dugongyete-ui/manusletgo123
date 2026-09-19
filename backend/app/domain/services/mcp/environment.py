"""MCP environment bootstrap — makes MCP ACTIVE per deployment environment.

The MCP infrastructure (``MCPClientManager`` / ``MCPToolkit`` / the
``ManusMCPExecutor`` fallback) has always existed, but it stayed dormant
whenever ``settings.mcp_config_path`` pointed at a file that did not exist
(``FileMCPRepository`` silently returns an empty config then).

This module closes that gap:

1. ``detect_environment()`` classifies the deployment host:
   - ``replit`` — real Replit host (REPLIT_* markers)
   - ``e2b``    — E2B runtime markers (config only; the sandbox factory's
                  host guard still decides whether E2B is ever touched)
   - ``zai``    — z.ai container / local dev (default)

2. ``build_default_mcp_config()`` composes a per-environment server set.
   The bundled ``filesystem_server.py`` is a self-contained stdio MCP server
   running on the SAME interpreter as the backend (no npm download needed),
   scoped to the sandbox user-home root with protected paths refused —
   preserving user isolation.

3. ``ensure_mcp_config()`` writes the generated config when the configured
   ``mcp.json`` is MISSING. An existing file is ALWAYS respected — the user
   owns their MCP setup. Every failure is swallowed (logged only): MCP must
   never break chat startup.

Config shape follows the project's ``mcp.json.example`` (which mirrors the
official ``mcpServers`` layout studied in the Claude Code audit):
``{"mcpServers": {name: {command, args, transport, enabled, env, description}}}``
"""

from __future__ import annotations

import json
import logging
import os
import sys
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

# Bundled stdio MCP server shipped with the backend (no external downloads).
# environment.py = backend/app/domain/services/mcp/environment.py
# parents[4] = backend/  →  backend/mcp_servers/filesystem_server.py
SERVER_SCRIPT = Path(__file__).resolve().parents[4] / "mcp_servers" / "filesystem_server.py"

# Replit host markers (same vocabulary as the sandbox factory host guard).
_REPLIT_MARKERS = (
    "REPLIT_ENVIRONMENT",
    "REPLIT_DEVBOX_ID",
    "REPLIT_DEPLOYMENT",
    "REPL_ID",
    "REPL_SLUG",
    "REPL_OWNER",
)
# E2B runtime markers.
_E2B_MARKERS = ("E2B_SANDBOX_ID", "E2B_RUNTIME", "E2B_SANDBOX")


def detect_environment() -> str:
    """Classify the deployment host: ``replit`` | ``e2b`` | ``zai``."""
    if any(os.environ.get(marker) for marker in _REPLIT_MARKERS):
        return "replit"
    if any(os.environ.get(marker) for marker in _E2B_MARKERS):
        return "e2b"
    return "zai"


def _protected_paths(settings) -> str:
    raw = getattr(settings, "sandbox_protected_paths", "") or ""
    return raw if isinstance(raw, str) else ",".join(raw)


def build_default_mcp_config(settings=None) -> Dict[str, Any]:
    """Compose the environment-appropriate default MCP server set.

    The bundled filesystem server:
    - runs on the backend interpreter (``sys.executable`` — guaranteed to
      have the ``mcp`` package installed via pyproject);
    - is confined to ``USER_HOME_ROOT`` (the same per-user home root the
      sandbox isolates users under);
    - refuses paths under ``SANDBOX_PROTECTED_PATHS`` (project source never
      reachable through MCP);
    - stays DISABLED when the server script is somehow missing — a config
      entry pointing at nothing would just log an error per run.
    """
    if settings is None:
        from app.core.config import get_settings

        settings = get_settings()

    env = {
        "DZECK_MCP_USER_ROOT": getattr(settings, "user_home_root", "") or "",
        "DZECK_MCP_PROTECTED": _protected_paths(settings),
        "DZECK_MCP_MAX_BYTES": "2000000",
    }

    servers: Dict[str, Any] = {}
    if SERVER_SCRIPT.exists():
        servers["dzeck-fs"] = {
            "transport": "stdio",
            "command": sys.executable,
            "args": [str(SERVER_SCRIPT)],
            "env": env,
            "enabled": True,
            "description": (
                "Bundled MCP filesystem server (stdio) — sandbox-scoped "
                f"file operations for the {detect_environment()} environment"
            ),
        }
    else:  # pragma: no cover — script ships with the repo
        logger.warning("Bundled MCP server script missing: %s", SERVER_SCRIPT)

    return {"mcpServers": servers}


def ensure_mcp_config(settings=None) -> Optional[Path]:
    """Activate MCP by materialising ``mcp.json`` when it does not exist.

    Returns the written path, or None when the existing user config is
    respected (or writing failed — MCP must never break the run).
    """
    if settings is None:
        from app.core.config import get_settings

        settings = get_settings()

    try:
        config_path = Path(settings.mcp_config_path)
        if config_path.exists():
            return None  # user-owned config wins — nothing to do

        config = build_default_mcp_config(settings)
        if not config["mcpServers"]:
            return None

        config_path.parent.mkdir(parents=True, exist_ok=True)
        config_path.write_text(json.dumps(config, indent=2, ensure_ascii=False))
        logger.info(
            "MCP activated for %s environment — wrote default config to %s (%d server(s))",
            detect_environment(),
            config_path,
            len(config["mcpServers"]),
        )
        return config_path
    except Exception:  # noqa: BLE001 — bootstrap is best-effort by contract
        logger.warning("MCP config bootstrap skipped (non-fatal)", exc_info=True)
        return None
