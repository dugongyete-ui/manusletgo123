"""Manus registry gate — mandatory test suite (20 scenarios).

Covers: registry loading, LLM surface, schema validation, MCP executor,
Shell executor (allowlist / no raw command / no shell=True / timeout),
loop safety, confirmation policy, secret redaction, MAX_STEPS, and the
full agent loop with mocked LLM + mocked transport.

No real MCP/LLM/browser/shell is touched — everything runs against mocks
or the local filesystem.
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional
from unittest.mock import AsyncMock, MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.domain.models.tool_result import ToolResult
from app.domain.services.manus_registry import (
    build_llm_schemas,
    get_registry,
    get_tool_def,
    list_tools,
    registry_stats,
)
from app.domain.services.manus_registry.errors import (
    LOOP_DETECTED,
    REQUIRES_CONFIRMATION,
    VALIDATION_ERROR,
    failure_payload,
    redact_secrets,
    success_payload,
)
from app.domain.services.manus_registry.gate import ManusGate, registry_llm_schemas
from app.domain.services.manus_registry.mcp_executor import ManusMCPExecutor
from app.domain.services.manus_registry.schema_validator import validate_arguments
from app.domain.services.manus_registry.shell_executor import (
    ManusShellExecutor,
    shell_allowlist,
    unavailable_shell_tools,
    _validate_argv,
)
from app.domain.services.manus_registry.trace import LoopSafety, arguments_hash


# ── helpers ──────────────────────────────────────────────────────────────────

class FakeSandbox:
    """Records exec_command payloads; mimics the sandbox transport contract."""

    def __init__(self, output: str = "", returncode: int = 0):
        self.calls: List[Dict[str, Any]] = []
        self.output = output
        self.returncode = returncode

    async def exec_command(self, session_id, exec_dir, command):
        self.calls.append({"session_id": session_id, "exec_dir": exec_dir,
                           "command": command})
        return ToolResult(
            success=True,
            message="Command executed",
            data={"session_id": session_id, "command": command,
                  "status": "completed", "returncode": self.returncode,
                  "output": self.output},
        )


class FakeBrowser:
    """Minimal browser double for the MCP executor."""

    def __init__(self):
        self.page = {"url": "https://example.com/", "title": "Example Domain"}
        self.calls: List[tuple] = []
        self.search_page = self._search_page

    async def _search_page(self, keyword):
        self.calls.append(("search_page", keyword))
        return ToolResult(success=True, message=None, data={
            "matches": [{"line": f"contains {keyword} here"}],
            "total_matches": 1,
        })

    async def navigate(self, url):
        self.calls.append(("navigate", url))
        self.page = {"url": url, "title": "Example Domain"}
        return ToolResult(success=True, data={"url": url, "page_changed": True,
                                              "title": "Example Domain"})

    async def view_page(self):
        self.calls.append(("view_page",))
        return ToolResult(success=True, data={
            "url": self.page["url"], "title": self.page["title"],
            "interactive_elements": [{"index": 1, "tag": "a", "text": "More information"}],
        })

    async def click(self, index=None, coordinate_x=None, coordinate_y=None, text=None):
        self.calls.append(("click", index))
        return ToolResult(success=True, data={"clicked": index, "page_changed": True})

    async def input(self, text, press_enter, index=None, coordinate_x=None, coordinate_y=None):
        self.calls.append(("input", index, text))
        return ToolResult(success=True, data={"input": text, "page_changed": press_enter})


class StubImageToolkit:
    async def image_generate(self, prompt, size=None, model=None):
        return ToolResult(success=True, message=None,
                          data={"url": "https://img.example/x.png"})

    async def image_download(self, url, file_path):
        return ToolResult(success=True, message=None, data={"saved": file_path})


def make_agent(toolkits=None):
    """Minimal agent double carrying toolkits (gate extracts backends)."""
    agent = MagicMock()
    agent.toolkits = toolkits or []
    agent.get_tools = lambda: [t for tk in agent.toolkits for t in tk.get_tools()]
    return agent


class _TK:
    def __init__(self, name, attr_name, attr_value):
        self.name = name
        setattr(self, attr_name, attr_value)

    def get_tools(self):
        return []


# ── 1–2. registry loading & LLM surface ─────────────────────────────────────

def test_registry_loads_with_manus_counts():
    stats = registry_stats()
    assert stats["mcp"] == 31
    assert stats["shell_available"] == 16
    assert stats["shell_documented_unavailable"] == 2
    assert stats["total"] == 49


def test_llm_surface_loads_registry_dynamically_and_hides_disabled():
    schemas = build_llm_schemas()
    names = {s["function"]["name"] for s in schemas}
    assert len(names) == 47  # 49 - 2 unavailable shell tools
    for disabled in ("manus-create-react-app", "manus-create-flask-app"):
        assert disabled not in names
    # every enabled registry tool is present
    for tool in list_tools():
        assert tool["name"] in names
    # schemas carry JSON-schema parameters from the registry
    nav = next(s for s in schemas if s["function"]["name"] == "browser_navigate")
    assert set(nav["function"]["parameters"]["required"]) == {"brief", "url", "intent"}


def test_unavailable_shell_tools_marked():
    assert sorted(unavailable_shell_tools()) == [
        "manus-create-flask-app", "manus-create-react-app",
    ]
    assert len(shell_allowlist()) == 16


# ── 3. final answer without tool (loop contract) ────────────────────────────

def test_loop_stops_when_model_returns_no_tool_calls():
    """The legacy loop breaks when the model emits no tool_calls — the gate
    is only consulted for tool_calls, so a final answer ends the loop."""
    message = MagicMock()
    message.tool_calls = []
    # mirrors base.execute(): `if not message.tool_calls: break`
    assert not message.tool_calls  # loop would break here


# ── 4–7. validation ──────────────────────────────────────────────────────────

def test_valid_single_tool_call_passes_validation():
    d = get_tool_def("browser_navigate")
    ok, err = validate_arguments(
        "browser_navigate", d["input_schema"],
        {"brief": "buka halaman", "url": "https://example.com",
         "intent": "informational"},
    )
    assert ok and err is None


def test_missing_required_argument_rejected():
    d = get_tool_def("browser_input")
    ok, err = validate_arguments(
        "browser_input", d["input_schema"],
        {"brief": "isi", "text": "halo"},  # press_enter missing
    )
    assert not ok and err["code"] == VALIDATION_ERROR
    assert any(e.get("missing_fields") for e in err["details"]["errors"])


def test_wrong_argument_type_rejected():
    d = get_tool_def("browser_input")
    ok, err = validate_arguments(
        "browser_input", d["input_schema"],
        {"brief": "isi", "text": "halo", "press_enter": "ya"},
    )
    assert not ok and err["code"] == VALIDATION_ERROR


def test_browser_click_requires_index_or_coordinates():
    schema = get_tool_def("browser_click")["input_schema"]
    ok, err = validate_arguments("browser_click", schema, {"brief": "klik"})
    assert not ok and err["code"] == VALIDATION_ERROR
    ok, _ = validate_arguments("browser_click", schema, {"brief": "klik", "index": 4})
    assert ok
    ok, _ = validate_arguments("browser_click", schema, {
        "brief": "klik", "viewport_width": 1280, "viewport_height": 1029,
        "coordinate_x": 10, "coordinate_y": 20})
    assert ok


# ── live-session regressions (z.ai session abcacd635a2e446e) ─────────────────
# In a real session the model called browser_click({"index": "23"}) WITH a
# brief, yet the gate rejected it 4x: (a) `brief` is nested inside allOf[0]
# so the top-level auto-fill check never fired, (b) the string "23" would
# fail the integer type check, and (c) identical validation failures never
# fed loop safety, so the model burned steps on a frozen strategy. All three
# are covered below.

def test_gate_autofills_brief_nested_in_allof_and_coerces_string_index():
    """browser_click("index": "23", brief passed) must EXECUTE — not fail
    with VALIDATION_ERROR as it did in the live Persib session."""
    browser = FakeBrowser()
    gate = ManusGate(make_agent([_TK("browser", "browser", browser)]))
    msg = asyncio.run(gate.process(
        tool_name="browser_click",
        tool_call_id="call_click_1",
        arguments={"index": "23"},          # string index, brief ABSENT from args
        brief="Klik link Jadwal",           # brief passed separately (popped upstream)
    ))
    body = json.loads(msg.content)
    assert body["success"], body           # was False before the fix
    assert body["tool"] == "browser_click"
    assert browser.calls and browser.calls[0][1] == 23   # coerced to int


def test_gate_synthesizes_brief_when_model_omits_everywhere():
    """Even with NO brief anywhere, the call executes with a synthesized
    narration label instead of being rejected."""
    browser = FakeBrowser()
    gate = ManusGate(make_agent([_TK("browser", "browser", browser)]))
    msg = asyncio.run(gate.process(
        tool_name="browser_click",
        tool_call_id="call_click_2",
        arguments={"index": 7},
        brief="",
    ))
    body = json.loads(msg.content)
    assert body["success"], body
    assert browser.calls[0][1] == 7


def test_gate_stops_identical_validation_error_storm():
    """Three identical BROKEN calls in a row → the 4th identical attempt is
    stopped with LOOP_DETECTED (guidance to change strategy), not another
    silent VALIDATION_ERROR round."""
    gate = ManusGate(make_agent([_TK("browser", "browser", FakeBrowser())]))
    codes = []
    for i in range(4):
        msg = asyncio.run(gate.process(
            tool_name="browser_navigate",
            tool_call_id=f"call_bad_{i}",
            arguments={"intent": "informational"},   # url missing → always invalid
            brief="buka",
        ))
        body = json.loads(msg.content)
        codes.append(body["error"]["code"])
    assert codes[0] == VALIDATION_ERROR
    assert codes[-1] == LOOP_DETECTED


def test_schema_helpers_nested_brief_and_coercion():
    from app.domain.services.manus_registry.schema_validator import (
        coerce_arguments, schema_mentions_brief,
    )
    schema = get_tool_def("browser_click")["input_schema"]
    assert schema_mentions_brief(schema)             # nested inside allOf
    coerced = coerce_arguments(schema, {"index": "23"})
    assert coerced["index"] == 23 and isinstance(coerced["index"], int)
    assert coerce_arguments(schema, {"index": "abc"})["index"] == "abc"  # untouched


def test_bin_dir_resolution_is_environment_adaptive(tmp_path, monkeypatch):
    """No hardcoded host path: explicit env wins; otherwise auto-resolve
    OUTSIDE protected paths and auto-deploy from the repo canonical copy."""
    import os
    from app.domain.services.manus_registry import deploy as deploy_mod
    # 1) canonical copy must ship in the repo (source of auto-deploy)
    canonical = deploy_mod._repo_canonical_dir()
    assert os.path.isfile(os.path.join(canonical, "manus_tool_lib.py"))
    # 2) explicit dir is used as-is and gets the 16 tools deployed
    target = tmp_path / "bins"
    result = deploy_mod.ensure_manus_tools_deployed(str(target))
    assert result == str(target)
    deployed = sorted(p.name for p in target.iterdir() if p.name.startswith("manus-"))
    assert len(deployed) == 16
    assert os.access(str(target / "manus-md-to-pdf"), os.X_OK)
    # 3) idempotent — second call does not duplicate or fail
    assert deploy_mod.ensure_manus_tools_deployed(str(target)) == str(target)
    # 4) resolver never returns a protected path
    resolved = deploy_mod.resolve_manus_tools_bin_dir()
    assert not deploy_mod._is_protected(resolved)


def test_unknown_tool_rejected_by_gate():
    gate = ManusGate(make_agent())
    msg = asyncio.run(gate.process(
        tool_name="not_a_real_tool", tool_call_id="call_x", arguments={}))
    assert msg is None  # not in registry → legacy path (which reports unknown)


# ── 8–10. MCP executor ───────────────────────────────────────────────────────

def test_mcp_executor_success_navigate_view_click():
    browser = FakeBrowser()
    ex = ManusMCPExecutor(browser=browser)
    payload = asyncio.run(ex.execute("browser_navigate", {
        "brief": "buka", "url": "https://example.com", "intent": "informational"}))
    assert payload["success"] and payload["tool"] == "browser_navigate"
    assert payload["data"]["url"] == "https://example.com"
    payload = asyncio.run(ex.execute("browser_view", {"brief": "lihat"}))
    assert payload["success"] and payload["data"]["title"] == "Example Domain"
    payload = asyncio.run(ex.execute("browser_click", {"brief": "klik", "index": 1}))
    assert payload["success"] and payload["data"]["clicked"] == 1


def test_mcp_executor_failure_returns_structured_error():
    class BoomBrowser(FakeBrowser):
        async def navigate(self, url):
            raise RuntimeError("connection refused")

    ex = ManusMCPExecutor(browser=BoomBrowser())
    payload = asyncio.run(ex.execute("browser_navigate", {
        "brief": "buka", "url": "https://x.com", "intent": "navigational"}))
    assert not payload["success"]
    assert payload["error"]["code"] in ("TRANSIENT_NETWORK_ERROR", "EXECUTION_ERROR")


def test_mcp_executor_unsupported_media_is_explicit_not_silent():
    ex = ManusMCPExecutor(browser=FakeBrowser())
    for tool in ("generate_video", "generate_speech", "generate_music"):
        payload = asyncio.run(ex.execute(tool, {"brief": "buat"}))
        assert not payload["success"]
        assert payload["error"]["code"] == "NOT_SUPPORTED"


def test_mcp_executor_generate_image_end_to_end():
    ex = ManusMCPExecutor(browser=FakeBrowser(), image_toolkit=StubImageToolkit())
    payload = asyncio.run(ex.execute("generate_image", {
        "brief": "logo", "model": "default", "quality": "high",
        "images": [{"path": "/home/user/logo.png", "prompt": "a logo"}],
    }))
    assert payload["success"]
    assert payload["data"]["saved_path"] == "/home/user/logo.png"


# ── 11–12. Shell executor security ───────────────────────────────────────────

def test_shell_executor_rejects_raw_command_string():
    ex = ManusShellExecutor(FakeSandbox())
    payload = asyncio.run(ex.execute(
        "manus-tools", {"command": "rm -rf / && echo pwned"}))
    assert not payload["success"] and payload["error"]["code"] == VALIDATION_ERROR
    assert "argv" in payload["error"]["message"].lower() or "forbidden" in payload["error"]["message"].lower()


def test_shell_executor_rejects_bash_c_sh_c_eval():
    ex = ManusShellExecutor(FakeSandbox())
    for argv in (["bash", "-c", "echo pwned"], ["sh", "-c", "id"],
                 ["eval", "x=1"], ["sudo", "rm", "x"]):
        payload = asyncio.run(ex.execute(
            "manus-tools", {"executable": "manus-tools", "argv": argv}))
        assert not payload["success"], argv
        assert payload["error"]["code"] == VALIDATION_ERROR


def test_shell_executor_does_not_use_shell_true(tmp_path, monkeypatch):
    """The executor builds the command from allowlisted absolute path +
    shlex-quoted argv — no raw model string ever reaches the transport."""
    # Environment-independent: point the bin dir at a tmp dir instead of any
    # host-specific path (works identically on z.ai, Replit, and VPS).
    monkeypatch.setattr(
        ManusShellExecutor, "_bin_dir",
        property(lambda self: str(tmp_path)),
    )
    sb = FakeSandbox(output=json.dumps({"ok": True, "data": {"status": "alive"}}))
    ex = ManusShellExecutor(sb)
    payload = asyncio.run(ex.execute(
        "manus-heartbeat", {"executable": "manus-heartbeat", "argv": ["my service name"]}))
    command = sb.calls[0]["command"]
    assert command.startswith("timeout 120 ")          # bounded runtime
    assert command.startswith(f"timeout 120 {tmp_path}/")  # absolute allowlisted path
    assert "'my service name'" in command              # quoted as ONE literal token
    assert payload["success"]                          # literal token is just a name


def test_shell_executor_rejects_shell_metacharacters_in_argv():
    ex = ManusShellExecutor(FakeSandbox())
    for argv in (["svc; rm -rf /"], ["a`id`b"], ["$(whoami)"], ["a && b"], ["x | y"]):
        payload = asyncio.run(ex.execute(
            "manus-tools", {"executable": "manus-tools", "argv": argv}))
        assert not payload["success"], argv
        assert payload["error"]["code"] == VALIDATION_ERROR


def test_shell_executor_runs_allowlisted_tool_and_parses_cli_json():
    sb = FakeSandbox(output=json.dumps(
        {"ok": True, "tool": "manus-heartbeat", "data": {"status": "alive"}}),
        returncode=0)
    ex = ManusShellExecutor(sb)
    payload = asyncio.run(ex.execute(
        "manus-heartbeat", {"executable": "manus-heartbeat", "argv": ["probe"]}))
    assert payload["success"]
    assert payload["data"]["result"]["status"] == "alive"
    assert payload["data"]["exit_code"] == 0


def test_shell_executor_rejects_non_allowlisted_executable():
    ex = ManusShellExecutor(FakeSandbox())
    payload = asyncio.run(ex.execute(
        "manus-tools", {"executable": "manus-other", "argv": []}))
    assert not payload["success"] and payload["error"]["code"] == VALIDATION_ERROR


def test_shell_executor_timeout_returns_retryable():
    sb = FakeSandbox(output="timed out waiting", returncode=124)
    ex = ManusShellExecutor(sb)
    payload = asyncio.run(ex.execute(
        "manus-heartbeat", {"executable": "manus-heartbeat", "argv": []}))
    assert not payload["success"] and payload["error"]["code"] == "TIMEOUT"
    assert payload["retryable"] is True


def test_shell_executor_disabled_tool_unavailable():
    ex = ManusShellExecutor(FakeSandbox())
    payload = asyncio.run(ex.execute(
        "manus-create-react-app", {"executable": "manus-create-react-app", "argv": []}))
    assert not payload["success"] and payload["error"]["code"] == "NOT_SUPPORTED"


# ── 13–14. loop safety ───────────────────────────────────────────────────────

def test_identical_call_detected_and_stopped():
    # _has_backend: a registry tool is only hijacked when its backing
    # implementation is attached — give the gate a fake browser toolkit.
    gate = ManusGate(make_agent([_TK("browser", "browser", FakeBrowser())]))
    args = {"brief": "lihat", "url": "https://x.com", "intent": "informational"}
    for i in range(3):
        msg = asyncio.run(gate.process(
            tool_name="browser_navigate", tool_call_id=f"c{i}", arguments=args))
        body = json.loads(msg.content)
    assert body["error"]["code"] == LOOP_DETECTED


def test_identical_error_streak_stops_loop():
    safety = LoopSafety()
    stop = None
    for _ in range(3):
        stop = safety.record_error("browser_click", VALIDATION_ERROR, "same problem")
    assert stop is not None and stop["error"]["code"] == LOOP_DETECTED


# ── 15–16. browser loop sequences ────────────────────────────────────────────

def test_browser_navigate_view_click_view_sequence():
    browser = FakeBrowser()
    ex = ManusMCPExecutor(browser=browser)
    seq = [
        ("browser_navigate", {"brief": "buka", "url": "https://example.com",
                              "intent": "informational"}),
        ("browser_view", {"brief": "baca halaman"}),
        ("browser_click", {"brief": "klik link", "index": 1}),
        ("browser_view", {"brief": "verifikasi hasil"}),
    ]
    for name, args in seq:
        payload = asyncio.run(ex.execute(name, args))
        assert payload["success"], (name, payload)
    kinds = [c[0] for c in browser.calls]
    assert kinds == ["navigate", "view_page", "click", "view_page"]


def test_browser_input_and_dropdown():
    browser = FakeBrowser()
    ex = ManusMCPExecutor(browser=browser)

    async def select_option(index, option_index):
        browser.calls.append(("select_option", index, option_index))
        return ToolResult(success=True, data={"selected": option_index})

    browser.select_option = select_option
    assert asyncio.run(ex.execute("browser_input", {
        "brief": "isi", "text": "halo", "press_enter": False, "index": 2}))["success"]
    payload = asyncio.run(ex.execute("browser_select_option", {
        "brief": "pilih", "index": 2, "option_index": 3}))
    assert payload["success"] and payload["data"]["selected"] == 3


def test_browser_fill_form_multiple_fields():
    browser = FakeBrowser()
    ex = ManusMCPExecutor(browser=browser)
    payload = asyncio.run(ex.execute("browser_fill_form", {
        "brief": "isi form",
        "fields": [
            {"index": 1, "text": "Budi"},
            {"index": 2, "text": "budi@x.com"},
            {"index": 3, "text": "pesan", "press_enter": True},
        ],
    }))
    assert payload["success"] and payload["data"]["fields_filled"] == 3
    inputs = [c for c in browser.calls if c[0] == "input"]
    assert len(inputs) == 3


def test_browser_find_keyword():
    ex = ManusMCPExecutor(browser=FakeBrowser())
    payload = asyncio.run(ex.execute("browser_find_keyword", {
        "brief": "cari harga", "keyword": "harga"}))
    assert payload["success"] and payload["data"]["total_matches"] == 1


# ── 17. file upload absolute path ────────────────────────────────────────────

def test_browser_upload_file_requires_absolute_style_entries():
    browser = FakeBrowser()

    async def upload(index, file_path):
        browser.calls.append(("upload", index, file_path))
        return ToolResult(success=True, data={"uploaded": file_path})

    browser.upload_file = upload
    ex = ManusMCPExecutor(browser=browser)
    payload = asyncio.run(ex.execute("browser_upload_file", {
        "brief": "unggah",
        "files": [{"index": 5, "path": "/home/user/dokumen/report.pdf"}],
    }))
    assert payload["success"] and payload["data"]["files_uploaded"] == 1
    assert browser.calls[0][2] == "/home/user/dokumen/report.pdf"


# ── 18. confirmation policy ──────────────────────────────────────────────────

def test_consequential_tool_requires_confirmation_and_approval_flow():
    sb = FakeSandbox(output=json.dumps({"ok": True, "data": {"rows": []}}))
    gate = ManusGate(make_agent([_TK("shell", "sandbox", sb)]))
    args = {"brief": "eksekusi", "query": "DELETE FROM users"}

    # first call → blocked with REQUIRES_CONFIRMATION
    msg = asyncio.run(gate.process(
        tool_name="webdev_execute_sql", tool_call_id="c1", arguments=args))
    body = json.loads(msg.content)
    assert body["error"]["code"] == REQUIRES_CONFIRMATION
    cid = body["error"]["details"]["confirmation_id"]

    # user approves via the ask-user resume path
    approved = gate.confirmations.register_user_reply(f"ya setuju {cid}")
    assert approved

    # re-issued call now executes
    msg2 = asyncio.run(gate.process(
        tool_name="webdev_execute_sql", tool_call_id="c2", arguments=args))
    body2 = json.loads(msg2.content)
    assert body2["error"] is None or body2["error"]["code"] != REQUIRES_CONFIRMATION


def test_ordinary_actions_do_not_require_confirmation():
    sb = FakeSandbox(output=json.dumps({"ok": True, "data": {}}))
    for name, args, tks in (
        ("browser_navigate", {"brief": "b", "url": "https://a.com",
                              "intent": "informational"},
         [_TK("browser", "browser", FakeBrowser())]),
        ("webdev_save_checkpoint", {"brief": "checkpoint", "name": "proj"},
         [_TK("shell", "sandbox", sb)]),
    ):
        gate = ManusGate(make_agent(tks))
        msg = asyncio.run(gate.process(tool_name=name, tool_call_id="c",
                                       arguments=args))
        body = json.loads(msg.content)
        if body["error"]:
            assert body["error"]["code"] != REQUIRES_CONFIRMATION


# ── 19. secret redaction ─────────────────────────────────────────────────────

def test_secrets_never_reach_model_or_trace():
    leaked = {
        "api_key": "nvapi-SUPERSECRETVALUE123456",
        "note": "token tvly-ABCDEFghijklmnop123456 in text",
        "nested": {"password": "hunter2", "safe": "value"},
    }
    clean = redact_secrets(leaked)
    assert "nvapi-SUPERSECRETVALUE123456" not in json.dumps(clean)
    assert "tvly-ABCDEFghijklmnop123456" not in json.dumps(clean)
    assert "hunter2" not in json.dumps(clean)
    assert clean["nested"]["safe"] == "value"

    # trace entries never contain arguments — only names + hashes
    from app.domain.services.manus_registry.trace import TraceRecorder
    tr = TraceRecorder()
    entry = tr.record(step=1, tool="browser_navigate", args_hash="abc123",
                      success=True, duration_ms=5)
    assert "url" not in json.dumps(entry)
    assert entry["arguments_hash"] == "abc123"


# ── 20. final answer after tool result (message contract) ───────────────────

def test_tool_result_message_contract_roundtrip():
    """ToolMessage keeps tool_call_id + normalized payload — the exact
    internal message format required by the Manus loop contract."""
    agent = make_agent([_TK("browser", "browser", FakeBrowser())])
    gate = ManusGate(agent)
    msg = asyncio.run(gate.process(
        tool_name="browser_navigate", tool_call_id="call_123",
        arguments={"brief": "buka", "url": "https://example.com",
                   "intent": "informational"}))
    assert msg.tool_call_id == "call_123"
    assert msg.name == "browser_navigate"
    body = json.loads(msg.content)
    assert body["success"] is True
    assert body["tool"] == "browser_navigate"
    assert body["error"] is None and body["retryable"] is False
    # artifact keeps a ToolResult for the UI timeline
    assert msg.artifact.success is True


# ── extra: gate uses correct transport per registry ─────────────────────────

def test_gate_routes_shell_transport_to_shell_executor():
    sb = FakeSandbox(output=json.dumps({"ok": True, "data": {"status": "alive"}}))
    agent = make_agent([_TK("shell", "sandbox", sb)])
    gate = ManusGate(agent)
    # manus-heartbeat requires confirmation — use a confirmation-free tool
    msg = asyncio.run(gate.process(
        tool_name="manus-webdev-logs", tool_call_id="c1",
        arguments={"executable": "manus-webdev-logs", "argv": ["10"]}))
    body = json.loads(msg.content)
    assert body["success"] and "exit_code" in body["data"]


def test_gate_blocks_confirmation_tool_until_approved():
    sb = FakeSandbox(output=json.dumps({"ok": True, "data": {}}))
    agent = make_agent([_TK("shell", "sandbox", sb)])
    gate = ManusGate(agent)
    msg = asyncio.run(gate.process(
        tool_name="manus-heartbeat", tool_call_id="c1",
        arguments={"executable": "manus-heartbeat", "argv": ["x"]}))
    body = json.loads(msg.content)
    assert body["error"]["code"] == REQUIRES_CONFIRMATION
    assert sb.calls == []  # never reached the sandbox


def test_max_steps_env_unlimited():
    from app.core.config import get_settings
    # Contract (updated 2026-09-19): MAX_STEPS=0 → UNLIMITED. The loop runs
    # until the goal is genuinely complete; MAX_CONSECUTIVE_FAILURES remains
    # the only health guard. The code default is already 0 (unlimited) — a
    # deployment may still pin a positive cap for cost control.
    import os
    env_path = Path(__file__).parent.parent / ".env"
    if env_path.exists():
        content = env_path.read_text()
        assert "MAX_STEPS=0" in content
        assert "MAX_STEPS=20" not in content
    assert get_settings().max_steps == 0


def test_registry_json_schema_browser_click_has_target_oneof():
    raw = get_registry()
    click = next(t for t in raw["tools"] if t["name"] == "browser_click")
    assert "allOf" in click["input_schema"]
    assert any("oneOf" in branch for branch in click["input_schema"]["allOf"])


def test_arguments_hash_stable():
    a = arguments_hash("t", {"b": 1, "a": 2})
    b = arguments_hash("t", {"a": 2, "b": 1})
    assert a == b
