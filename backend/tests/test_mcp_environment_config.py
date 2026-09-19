"""Tests — MCP environment bootstrap (Replit / E2B / z.ai).

Requirement: "mcp belum ada yang aktif kan, buat mcp nya dan mcp nya
mengikuti lingkungan Replit, E2b, dan khusus z.ai" — the bootstrap must
materialise a working mcp.json per environment, respect user-owned configs,
and never break startup.
"""

import json
import os

import pytest

from app.domain.models.mcp_config import MCPConfig
from app.domain.services.mcp.environment import (
    SERVER_SCRIPT,
    build_default_mcp_config,
    detect_environment,
    ensure_mcp_config,
)


class _FakeSettings:
    """Minimal Settings stand-in — avoids the lru-cached real one."""

    def __init__(self, tmp_path):
        self.mcp_config_path = str(tmp_path / "mcp.json")
        self.user_home_root = str(tmp_path / "users")
        self.sandbox_protected_paths = str(tmp_path / "protected-src")


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for marker in (
        "REPLIT_ENVIRONMENT", "REPLIT_DEVBOX_ID", "REPLIT_DEPLOYMENT",
        "REPL_ID", "REPL_SLUG", "REPL_OWNER",
        "E2B_SANDBOX_ID", "E2B_RUNTIME", "E2B_SANDBOX",
    ):
        monkeypatch.delenv(marker, raising=False)
    yield


def test_detect_environment_default_zai():
    assert detect_environment() == "zai"


def test_detect_environment_replit(monkeypatch):
    monkeypatch.setenv("REPLIT_ENVIRONMENT", "production")
    monkeypatch.setenv("REPL_ID", "abc")
    assert detect_environment() == "replit"


def test_detect_environment_e2b(monkeypatch):
    monkeypatch.setenv("E2B_SANDBOX_ID", "sbx-123")
    assert detect_environment() == "e2b"


def test_replit_wins_over_e2b(monkeypatch):
    monkeypatch.setenv("REPLIT_ENVIRONMENT", "production")
    monkeypatch.setenv("E2B_SANDBOX_ID", "sbx-123")
    assert detect_environment() == "replit"


def test_bundled_server_script_shipped():
    assert SERVER_SCRIPT.exists(), f"missing bundled MCP server: {SERVER_SCRIPT}"


def test_default_config_has_active_server(tmp_path):
    cfg = build_default_mcp_config(_FakeSettings(tmp_path))
    assert "dzeck-fs" in cfg["mcpServers"]
    server = cfg["mcpServers"]["dzeck-fs"]
    assert server["transport"] == "stdio"
    assert server["enabled"] is True
    assert server["command"]  # interpreter path present
    assert server["args"] == [str(SERVER_SCRIPT)]
    assert server["env"]["DZECK_MCP_USER_ROOT"] == str(tmp_path / "users")


def test_ensure_writes_config_when_missing(tmp_path):
    settings = _FakeSettings(tmp_path)
    assert not os.path.exists(settings.mcp_config_path)
    written = ensure_mcp_config(settings)
    assert written is not None and written.exists()
    # The written file must parse into the project's MCPConfig model.
    config = MCPConfig.model_validate_json(written.read_text())
    assert "dzeck-fs" in config.mcpServers
    assert config.mcpServers["dzeck-fs"].enabled is True


def test_ensure_respects_existing_user_config(tmp_path):
    settings = _FakeSettings(tmp_path)
    user_cfg = {"mcpServers": {"my-own": {"transport": "stdio", "command": "echo", "enabled": True}}}
    path = tmp_path / "mcp.json"
    path.write_text(json.dumps(user_cfg))
    assert ensure_mcp_config(settings) is None  # nothing overwritten
    assert "my-own" in json.loads(path.read_text())["mcpServers"]


def test_ensure_never_raises_on_unwritable_path(tmp_path):
    settings = _FakeSettings(tmp_path)
    settings.mcp_config_path = "/proc/definitely/not/writable/mcp.json"
    assert ensure_mcp_config(settings) is None  # swallowed, returns None


def test_bundled_server_boundary_denies_escape(tmp_path):
    """The bundled server refuses paths outside the user root."""
    pytest.importorskip("mcp")
    import sys

    sys.path.insert(0, str(SERVER_SCRIPT.parent))
    import filesystem_server as fs

    fs.USER_ROOT = tmp_path / "users"
    fs.USER_ROOT.mkdir(parents=True, exist_ok=True)

    inside = fs._check(fs.Path("subdir/file.txt"))
    assert inside.is_relative_to(fs.USER_ROOT)

    with pytest.raises(fs.PathDenied):
        fs._check(fs.Path("/etc/passwd"))

    protected = tmp_path / "protected-src"
    protected.mkdir(exist_ok=True)
    fs.PROTECTED = [protected]
    with pytest.raises(fs.PathDenied):
        fs._check(protected / "secret.py")
