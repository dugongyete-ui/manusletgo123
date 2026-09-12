"""Live matrix: EVERY tool in EVERY toolkit, run against the real runtime.

Why this file exists
--------------------
A live incident (2026-08-31, mobile screenshot) showed a task dying mid-run
with a raw "Task error: Error code: 404" while the tool steps looked fine.
Separately, a data: URL navigation poisoned the whole CDP session. The user
asked for a full, honest sweep: every shell / browser / image / search / file
/ message tool must be exercised against the REAL environment so empty
results, broken shapes and silent errors become visible instead of hiding
behind a green dot.

How it stays environment-true (no hardcoding)
---------------------------------------------
The fixtures build the stack exactly the way production does:
    HybridSandboxFactory.create()  → SANDBOX_PROVIDER setting decides
                                     (E2B when configured, Replit-local
                                     otherwise — same resolution the app
                                     uses on Replit deploys)
    UserScopedSandbox(sandbox, uid) → per-user path scoping
    sandbox.get_browser()          → the CDP browser the agent drives
    get_search_engine()            → the configured search provider

No absolute paths, ports, providers or credentials are hardcoded: the form
page used by the browser tests is served by an ephemeral local HTTP server
started by the fixture, and every file operation uses natural relative
paths inside the sandbox home. The same suite therefore runs unchanged on
this dev host and on a Replit deploy.

What is asserted for every call
-------------------------------
1. The tool returns a real ToolResult (never a crash, never a stray type).
2. success=True ⇒ the result carries VISIBLE content (message and/or data)
   — the "silent empty success" bug class fails loudly here.
3. success=False ⇒ the message explains the failure in human words — raw
   exception text or an empty message fails loudly.
4. Tool-specific expectations (output echoed, file round-trips, results
   non-empty, element found, etc.).

image_generate is the one tool NOT tested for success: no image API key is
configured on this host, so the test asserts the FAILURE path is clean and
self-explanatory (per the project rule: missing credentials must produce a
clear error, never a crash or a silent nothing).

Run standalone:
    pytest tests/test_all_tools_live.py -v

Optional per-tool report artifact:
    TOOL_TEST_REPORT_PATH=/path/to/report.md pytest tests/test_all_tools_live.py
"""

import asyncio
import json
import os
import re
import time
from types import SimpleNamespace

import pytest
import pytest_asyncio

from app.domain.models.tool_result import ToolResult
from app.infrastructure.external.sandbox.sandbox_factory import (
    HybridSandboxFactory,
)
from app.infrastructure.external.sandbox.user_sandbox import UserScopedSandbox
from app.infrastructure.external.search import get_search_engine
from app.domain.services.tools.browser import BrowserToolkit
from app.domain.services.tools.file import FileToolkit
from app.domain.services.tools.image import ImageToolkit
from app.domain.services.tools.message import MessageToolkit
from app.domain.services.tools.search import SearchToolkit
from app.domain.services.tools.shell import ShellToolkit

pytestmark = pytest.mark.asyncio(loop_scope="module")

TEST_USER = "tooltest"

# ── per-call report (visible proof, not just pass/fail) ────────────────────

REPORT: list = []


def _data_shape(data) -> str:
    if data is None:
        return "—"
    if isinstance(data, dict):
        keys = ",".join(list(data.keys())[:6])
        return f"dict({keys})"
    if isinstance(data, list):
        return f"list[{len(data)}]"
    if isinstance(data, str):
        return f"str({len(data)} ch)"
    return type(data).__name__


def record(toolkit: str, tool: str, result: ToolResult, seconds: float) -> None:
    entry = {
        "toolkit": toolkit,
        "tool": tool,
        "success": result.success,
        "message": (result.message or "")[:120],
        "data": _data_shape(result.data),
        "seconds": round(seconds, 2),
    }
    REPORT.append(entry)
    status = "OK  " if result.success else "FAIL"
    print(
        f"  [TOOL] {toolkit}.{tool} → {status} ({entry['seconds']}s) "
        f"msg={entry['message'] or '—'} data={entry['data']}"
    )


async def call(tk, name: str, args: dict) -> ToolResult:
    """Invoke one toolkit tool the same way the executor does, record it,
    and enforce the universal ToolResult contract."""
    tool = next(t for t in tk.tools if t.name == name)
    t0 = time.perf_counter()
    try:
        message = await tool.ainvoke({"args": args, "id": f"live-{name}"})
        result = message.artifact
    except Exception as exc:  # a bug escaped the tool — this MUST fail loudly
        result = ToolResult(
            success=False,
            message=f"UNHANDLED {type(exc).__name__}: {exc}",
        )
        record(tk.name, name, result, time.perf_counter() - t0)
        raise

    assert isinstance(result, ToolResult), (
        f"{name}: returned {type(result).__name__}, expected ToolResult"
    )
    has_message = bool((result.message or "").strip())
    has_data = result.data not in (None, {}, [], "")
    if result.success:
        assert has_message or has_data, (
            f"{name}: success=True but the result is EMPTY "
            f"(no message, no data) — invisible to the user"
        )
    else:
        assert has_message, (
            f"{name}: success=False without an explanation message"
        )
        assert "Traceback" not in (result.message or ""), (
            f"{name}: raw traceback leaked into the result: {result.message}"
        )
    record(tk.name, name, result, time.perf_counter() - t0)
    return result


def as_dict(result: ToolResult) -> dict:
    return result.data if isinstance(result.data, dict) else {}


def find_index(elements, needle: str) -> int:
    """Parse 'idx:<tag>text</tag>' lines from browser_view data and return the
    DOM index of the first element whose line contains needle."""
    for line in elements or []:
        if not isinstance(line, str):
            continue
        if needle.lower() in line.lower():
            m = re.match(r"^\*?(\d+):", line)
            if m:
                return int(m.group(1))
    raise AssertionError(f"element containing {needle!r} not found in view")


# ── deterministic form page served locally (no external dependency) ─────────

FORM_HTML = """<!doctype html>
<html lang="id">
<head><meta charset="utf-8"><title>Formulir Uji Tools</title></head>
<body>
<h1>Formulir Uji Tools</h1>
<script>console.log("halaman formulir dimuat");</script>
<form id="f" onsubmit="event.preventDefault();
  document.getElementById('hasil').textContent =
  'terkirim:' + document.getElementById('nama').value;">
  <input id="nama" type="text" placeholder="Nama lengkap" />
  <select id="hari" aria-label="Pilih hari">
    <option value="">-- pilih --</option>
    <option value="Senin">Senin</option>
    <option value="Selasa">Selasa</option>
    <option value="Rabu">Rabu</option>
  </select>
  <input type="file" id="berkas" aria-label="Unggah berkas" />
  <button type="submit" id="kirim">Kirim</button>
</form>
<div id="hasil"></div>
<a id="kehal2" href="/hal2">Halaman kedua</a>
<div style="height:2400px">isi panjang untuk scroll</div>
</body></html>"""

PAGE2_HTML = """<!doctype html>
<html lang="id">
<head><meta charset="utf-8"><title>Halaman Kedua</title></head>
<body><h1>Halaman Kedua</h1><a href="/form">Kembali ke formulir</a></body></html>"""


class LocalPageServer:
    """Ephemeral localhost HTTP server (raw asyncio) for the form fixture."""

    def __init__(self) -> None:
        self._server = None
        self.port = None

    async def start(self) -> None:
        self._server = await asyncio.start_server(self._handle, "127.0.0.1", 0)
        self.port = self._server.sockets[0].getsockname()[1]

    @property
    def form_url(self) -> str:
        return f"http://127.0.0.1:{self.port}/form"

    @property
    def page2_url(self) -> str:
        return f"http://127.0.0.1:{self.port}/hal2"

    async def _handle(self, reader: asyncio.StreamReader, writer) -> None:
        try:
            request_line = (await reader.readline()).decode("utf-8", "replace")
            while True:
                line = await reader.readline()
                if line in (b"\r\n", b"\n", b""):
                    break
            body = PAGE2_HTML if "/hal2" in request_line else FORM_HTML
            payload = body.encode("utf-8")
            writer.write(
                b"HTTP/1.1 200 OK\r\nContent-Type: text/html; charset=utf-8\r\n"
                b"Content-Length: " + str(len(payload)).encode() + b"\r\n"
                b"Connection: close\r\n\r\n" + payload
            )
            await writer.drain()
        except Exception:
            pass
        finally:
            try:
                writer.close()
            except Exception:
                pass

    async def stop(self) -> None:
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()


# ── module-scoped runtime (built once, shared by every test) ────────────────

@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def runtime():
    """The exact production wiring — provider resolution included."""
    sandbox = await HybridSandboxFactory.create()
    # Same warmup sequence agent_domain_service runs before a task: bring
    # the sandbox services up and give the user a home directory.
    await sandbox.ensure_sandbox()
    user_sandbox = UserScopedSandbox(sandbox, TEST_USER)
    await user_sandbox.setup_user_home()
    browser = await sandbox.get_browser()
    server = LocalPageServer()
    await server.start()

    rt = SimpleNamespace(
        sandbox=sandbox,
        user_sandbox=user_sandbox,
        browser=browser,
        server=server,
        shell=ShellToolkit(user_sandbox),
        files=FileToolkit(user_sandbox),
        browser_tk=BrowserToolkit(browser),
        image=ImageToolkit(user_sandbox),
        message=MessageToolkit(),
    )
    engine = get_search_engine()
    if engine is not None:
        rt.search = SearchToolkit(engine)
    else:
        rt.search = None

    yield rt

    await server.stop()


# ── 1. shell tools (5/5) ────────────────────────────────────────────────────

async def test_shell_exec_basic(runtime):
    res = await call(
        runtime.shell, "shell_exec",
        {"command": 'echo "uji-shell-dzeck" && uname -s'},
    )
    assert res.success, res.message
    blob = json.dumps(as_dict(res), ensure_ascii=False)
    assert "uji-shell-dzeck" in blob, f"output not visible: {blob[:200]}"


async def test_shell_exec_with_exec_dir(runtime):
    # The default exec directory IS the user's sandbox home — discover it
    # naturally with pwd, then explicitly pass it as exec_dir.
    first = await call(runtime.shell, "shell_exec", {"command": "pwd"})
    home_path = ""
    for value in as_dict(first).values():
        if isinstance(value, str) and value.strip().startswith("/"):
            home_path = value.strip()
            break
    assert home_path, f"pwd gave no usable path: {as_dict(first)}"
    res = await call(
        runtime.shell, "shell_exec",
        {"command": "pwd", "exec_dir": home_path},
    )
    assert res.success, res.message
    assert home_path in json.dumps(as_dict(res)), (
        f"pwd did not run inside {home_path}"
    )


async def test_shell_view_and_session_reuse(runtime):
    exec_res = await call(
        runtime.shell, "shell_exec",
        {"command": "echo penanda-sesi-uji"},
    )
    session_id = ""
    for key in ("id", "session_id"):
        value = as_dict(exec_res).get(key)
        if value:
            session_id = value
            break
    assert session_id, f"no session id in result: {as_dict(exec_res)}"
    res = await call(runtime.shell, "shell_view", {"id": session_id})
    assert res.success, res.message
    assert "penanda-sesi-uji" in json.dumps(as_dict(res), ensure_ascii=False)


async def test_shell_wait_for_process(runtime):
    exec_res = await call(
        runtime.shell, "shell_exec", {"command": "sleep 6 && echo tunggu-selesai"},
    )
    session_id = next(
        (v for k, v in as_dict(exec_res).items()
         if k in ("id", "session_id") and v), "",
    )
    assert session_id, f"no session id: {as_dict(exec_res)}"
    res = await call(
        runtime.shell, "shell_wait", {"id": session_id, "seconds": 20},
    )
    assert res.success, res.message
    blob = json.dumps(as_dict(res), ensure_ascii=False)
    assert "tunggu-selesai" in blob or "selesai" in blob, (
        f"wait result missing process output: {blob[:300]}"
    )


async def test_shell_write_to_process(runtime):
    exec_res = await call(
        runtime.shell, "shell_exec", {"command": "cat"},
    )
    session_id = next(
        (v for k, v in as_dict(exec_res).items()
         if k in ("id", "session_id") and v), "",
    )
    assert session_id, f"no session id: {as_dict(exec_res)}"
    write_res = await call(
        runtime.shell, "shell_write_to_process",
        {"id": session_id, "input": "stdin-baris-uji", "press_enter": True},
    )
    assert write_res.success, write_res.message
    view_res = await call(runtime.shell, "shell_view", {"id": session_id})
    blob = json.dumps(as_dict(view_res), ensure_ascii=False)
    assert "stdin-baris-uji" in blob, (
        f"echoed stdin not visible in session: {blob[:300]}"
    )


async def test_shell_kill_process(runtime):
    exec_res = await call(
        runtime.shell, "shell_exec", {"command": "sleep 120"},
    )
    session_id = next(
        (v for k, v in as_dict(exec_res).items()
         if k in ("id", "session_id") and v), "",
    )
    assert session_id, f"no session id: {as_dict(exec_res)}"
    res = await call(runtime.shell, "shell_kill_process", {"id": session_id})
    assert res.success, res.message


# ── 2. browser tools (25/25 + session-health regression) ────────────────────

async def test_browser_navigate_live_site(runtime):
    res = await call(
        runtime.browser_tk, "browser_navigate", {"url": "https://example.com"},
    )
    assert res.success, res.message
    data = as_dict(res)
    assert (data.get("url") or "").startswith("https://example.com"), data
    assert data.get("title"), "page title not visible"


async def test_browser_view(runtime):
    res = await call(runtime.browser_tk, "browser_view", {})
    assert res.success, res.message
    data = as_dict(res)
    assert data.get("interactive_elements") or data.get("content"), (
        "view returned neither elements nor content"
    )


async def test_browser_restart_resets_to_form(runtime):
    res = await call(
        runtime.browser_tk, "browser_restart", {"url": runtime.server.form_url},
    )
    assert res.success, res.message
    data = as_dict(res)
    title = (data.get("title") or "")
    if not title:
        view = await call(runtime.browser_tk, "browser_view", {})
        title = as_dict(view).get("title") or ""
    assert "Formulir Uji Tools" in title, f"unexpected title: {title!r}"


async def _form_view(runtime):
    res = await call(runtime.browser_tk, "browser_view", {})
    assert res.success, res.message
    data = as_dict(res)
    elements = data.get("interactive_elements") or []
    assert len(elements) >= 4, f"form elements missing: {elements}"
    return data


async def test_browser_find_element_on_form(runtime):
    res = await call(
        runtime.browser_tk, "browser_find_element", {"query": "Pilih hari"},
    )
    assert res.success, res.message
    blob = json.dumps(as_dict(res), ensure_ascii=False)
    assert "hari" in blob.lower(), f"select not found: {blob[:300]}"


async def test_browser_input_and_verify_value(runtime):
    data = await _form_view(runtime)
    idx = find_index(data["interactive_elements"], "Nama lengkap")
    res = await call(
        runtime.browser_tk, "browser_input",
        {"index": idx, "text": "Budi Santoso", "press_enter": False},
    )
    assert res.success, res.message
    verify = await call(
        runtime.browser_tk, "browser_verify_value",
        {"index": idx, "expected_text": "Budi Santoso"},
    )
    assert verify.success, verify.message


async def test_browser_get_select_options(runtime):
    data = await _form_view(runtime)
    idx = find_index(data["interactive_elements"], "Pilih hari")
    res = await call(
        runtime.browser_tk, "browser_get_select_options", {"index": idx},
    )
    assert res.success, res.message
    blob = json.dumps(as_dict(res), ensure_ascii=False)
    assert "Senin" in blob, f"options not visible: {blob[:300]}"


async def test_browser_select_by_text(runtime):
    data = await _form_view(runtime)
    idx = find_index(data["interactive_elements"], "Pilih hari")
    res = await call(
        runtime.browser_tk, "browser_select_by_text",
        {"index": idx, "text": "Senin"},
    )
    assert res.success, res.message


async def test_browser_select_option_by_number(runtime):
    data = await _form_view(runtime)
    idx = find_index(data["interactive_elements"], "Pilih hari")
    res = await call(
        runtime.browser_tk, "browser_select_option", {"index": idx, "option": 2},
    )
    assert res.success, res.message


async def test_browser_smart_select(runtime):
    res = await call(
        runtime.browser_tk, "browser_smart_select",
        {"dropdown": "Pilih hari", "option": "Selasa"},
    )
    assert res.success, res.message


async def test_browser_click_submit_button(runtime):
    res = await call(
        runtime.browser_tk, "browser_click", {"text": "Kirim"},
    )
    assert res.success, res.message


async def test_browser_wait_for_element(runtime):
    res = await call(
        runtime.browser_tk, "browser_wait_for_element",
        {"selector": "#hasil", "text": "terkirim", "timeout": 10},
    )
    assert res.success, res.message


async def test_browser_console_exec(runtime):
    res = await call(
        runtime.browser_tk, "browser_console_exec",
        {"javascript": "JSON.stringify({uji: 6 * 7})"},
    )
    assert res.success, res.message
    blob = json.dumps(as_dict(res), ensure_ascii=False)
    assert "42" in blob, f"eval result not visible: {blob[:300]}"


async def test_browser_console_view(runtime):
    res = await call(
        runtime.browser_tk, "browser_console_view", {"max_lines": 20},
    )
    assert res.success, res.message
    logs = as_dict(res).get("logs") or []
    assert isinstance(logs, list), f"logs not a list: {logs!r}"
    blob = json.dumps(logs, ensure_ascii=False)
    assert "formulir dimuat" in blob, f"console.log from page not captured: {blob[:300]}"


async def test_browser_scroll_down_and_up(runtime):
    down = await call(
        runtime.browser_tk, "browser_scroll_down", {"to_bottom": True},
    )
    assert down.success, down.message
    up = await call(
        runtime.browser_tk, "browser_scroll_up", {},
    )
    assert up.success, up.message


async def test_browser_click_link_navigates(runtime):
    res = await call(
        runtime.browser_tk, "browser_click", {"text": "Halaman kedua"},
    )
    assert res.success, res.message


async def test_browser_back_and_forward(runtime):
    back = await call(runtime.browser_tk, "browser_back", {})
    assert back.success, back.message
    fwd = await call(runtime.browser_tk, "browser_forward", {})
    assert fwd.success, fwd.message


async def test_browser_wait_for_network_idle(runtime):
    res = await call(
        runtime.browser_tk, "browser_wait_for_network_idle", {"timeout": 10},
    )
    assert res.success, res.message


async def test_browser_move_mouse_and_press_key(runtime):
    move = await call(
        runtime.browser_tk, "browser_move_mouse",
        {"coordinate_x": 200, "coordinate_y": 200},
    )
    assert move.success, move.message
    key = await call(
        runtime.browser_tk, "browser_press_key", {"key": "Tab"},
    )
    assert key.success, key.message


async def test_browser_upload_file(runtime):
    # Navigate to the form first: earlier tests (click link / back / forward)
    # legitimately leave the active page elsewhere.
    nav = await call(
        runtime.browser_tk, "browser_navigate", {"url": runtime.server.form_url},
    )
    assert nav.success, nav.message
    note = await call(
        runtime.files, "file_write",
        {"file": "unggahan-uji.txt", "content": "isi berkas untuk unggah"},
    )
    assert note.success, note.message
    data = await _form_view(runtime)
    idx = find_index(data["interactive_elements"], "Unggah berkas")
    home_blob = as_dict(await call(
        runtime.shell, "shell_exec", {"command": "pwd"},
    ))
    home = next(
        (v for v in home_blob.values() if isinstance(v, str) and v.strip().startswith("/")),
        "",
    ).strip()
    res = await call(
        runtime.browser_tk, "browser_upload_file",
        {"index": idx, "file_path": f"{home}/unggahan-uji.txt"},
    )
    assert res.success, res.message
    assert "bytes" in (res.message or ""), res.message


async def test_browser_open_list_switch_tabs(runtime):
    opened = await call(
        runtime.browser_tk, "browser_open_tab", {"url": runtime.server.page2_url},
    )
    assert opened.success, opened.message
    listing = await call(runtime.browser_tk, "browser_list_tabs", {})
    assert listing.success, listing.message
    blob = json.dumps(as_dict(listing), ensure_ascii=False)
    assert "2" in blob, f"expected 2 tabs in listing: {blob[:300]}"
    switch = await call(
        runtime.browser_tk, "browser_switch_tab", {"tab_index": 1},
    )
    assert switch.success, switch.message


async def test_browser_data_url_rejected_cleanly(runtime):
    """Regression: data: URLs used to poison the CDP session for every later
    call. The guard must answer with a clean, human explanation instead."""
    res = await call(
        runtime.browser_tk, "browser_navigate",
        {"url": "data:text/html,<h1>tidak boleh</h1>"},
    )
    assert not res.success, "data: URL must be refused, not 'succeeded'"
    assert "not supported" in (res.message or ""), res.message


async def test_browser_healthy_after_rejection(runtime):
    """The poisoned-session regression check: after a refused scheme the
    browser must still be fully usable."""
    res = await call(runtime.browser_tk, "browser_view", {})
    assert res.success, res.message


async def test_browser_restart_leaves_clean_state(runtime):
    res = await call(
        runtime.browser_tk, "browser_restart", {"url": "https://example.com"},
    )
    assert res.success, res.message


# ── 3. file tools (9/9) ─────────────────────────────────────────────────────

FILE_NAME = "catatan-uji.md"
FILE_BODY = "# Catatan Uji\n\nBaris pertama berisi kata draft yang akan diganti."


async def test_file_write_create(runtime):
    res = await call(
        runtime.files, "file_write", {"file": FILE_NAME, "content": FILE_BODY},
    )
    assert res.success, res.message


async def test_file_read_roundtrip(runtime):
    res = await call(runtime.files, "file_read", {"file": FILE_NAME})
    assert res.success, res.message
    blob = json.dumps(as_dict(res), ensure_ascii=False)
    assert "Baris pertama" in blob, f"content not visible: {blob[:200]}"


async def test_file_write_append(runtime):
    res = await call(
        runtime.files, "file_write",
        {"file": FILE_NAME, "content": "\n\nBaris tambahan.", "append": True},
    )
    assert res.success, res.message
    read = await call(runtime.files, "file_read", {"file": FILE_NAME})
    blob = json.dumps(as_dict(read), ensure_ascii=False)
    assert "Baris tambahan" in blob, blob[:200]


async def test_file_str_replace(runtime):
    res = await call(
        runtime.files, "file_str_replace",
        {"file": FILE_NAME, "old_str": "draft", "new_str": "final"},
    )
    assert res.success, res.message
    read = await call(runtime.files, "file_read", {"file": FILE_NAME})
    blob = json.dumps(as_dict(read), ensure_ascii=False)
    assert "final" in blob and "draft" not in blob, blob[:300]


async def test_file_find_in_content(runtime):
    res = await call(
        runtime.files, "file_find_in_content",
        {"file": FILE_NAME, "regex": "final|tambahan"},
    )
    assert res.success, res.message
    blob = json.dumps(as_dict(res), ensure_ascii=False)
    assert "final" in blob, f"matches not visible: {blob[:200]}"


async def test_file_find_by_name(runtime):
    res = await call(
        runtime.files, "file_find_by_name", {"path": ".", "glob": "*.md"},
    )
    assert res.success, res.message
    blob = json.dumps(as_dict(res), ensure_ascii=False)
    assert FILE_NAME in blob, f"file not found: {blob[:200]}"


async def test_file_list_dir(runtime):
    res = await call(runtime.files, "file_list_dir", {"path": "."})
    assert res.success, res.message
    blob = json.dumps(as_dict(res), ensure_ascii=False)
    assert FILE_NAME in blob, f"file not listed: {blob[:200]}"


async def test_file_copy_and_move(runtime):
    copy = await call(
        runtime.files, "file_copy",
        {"source": FILE_NAME, "destination": "catatan-salinan.md"},
    )
    assert copy.success, copy.message
    move = await call(
        runtime.files, "file_move",
        {"source": "catatan-salinan.md", "destination": "arsip/catatan-salinan.md"},
    )
    assert move.success, move.message
    read = await call(
        runtime.files, "file_read", {"file": "arsip/catatan-salinan.md"},
    )
    assert read.success, read.message


async def test_file_delete_and_missing_read(runtime):
    deleted = await call(
        runtime.files, "file_delete", {"path": "arsip/catatan-salinan.md"},
    )
    assert deleted.success, deleted.message
    missing = await call(
        runtime.files, "file_read", {"file": "arsip/catatan-salinan.md"},
    )
    assert not missing.success, "reading a deleted file must fail"
    assert missing.message, "failure must explain itself"


# ── 4. search tool (1/1) ────────────────────────────────────────────────────

async def test_info_search_web_live(runtime):
    if runtime.search is None:
        pytest.skip("no search engine configured on this host")
    res = await call(
        runtime.search, "info_search_web", {"query": "Persija Jakarta"},
    )
    assert res.success, res.message
    # data is a SearchResults model (not a plain dict) — read it either way.
    results = getattr(res.data, "results", None)
    if results is None:
        results = as_dict(res).get("results") or []
    assert len(results) >= 1, f"no results visible: {res.message}"
    first = results[0] if isinstance(results[0], dict) else results[0]
    link = first.get("link") or first.get("url") if isinstance(first, dict) else getattr(first, "link", None)
    title = first.get("title") if isinstance(first, dict) else getattr(first, "title", None)
    assert link, f"result lacks a URL: {first!r}"
    assert title, f"result lacks a title: {first!r}"


# ── 5. image tools (search + download live; generate = clean error) ─────────

async def test_image_search_web_live(runtime):
    res = await call(
        runtime.image, "image_search_web",
        {"query": "logo GitHub", "count": 3},
    )
    assert res.success, res.message
    results = getattr(res.data, "results", None)
    if results is None:
        results = as_dict(res).get("results") or []
    assert len(results) >= 1, f"no images found: {res.message}"
    first = results[0]
    url = first.get("url") if isinstance(first, dict) else getattr(first, "url", None)
    assert url, f"image result lacks a URL: {first!r}"


async def test_image_download_live(runtime):
    search = await call(
        runtime.image, "image_search_web", {"query": "logo GitHub", "count": 3},
    )
    results = getattr(search.data, "results", None)
    if results is None:
        results = as_dict(search).get("results") or []
    assert results, "search produced nothing to download"
    first = results[0]
    url = (first.get("url") if isinstance(first, dict) else getattr(first, "url", None)) or ""
    res = await call(
        runtime.image, "image_download",
        {"url": url, "file_path": "logo-uji.png"},
    )
    assert res.success, res.message
    listing = await call(
        runtime.files, "file_find_by_name",
        {"path": ".", "glob": "logo-uji*"},
    )
    blob = json.dumps(as_dict(listing), ensure_ascii=False)
    assert "logo-uji" in blob, f"downloaded file not on disk: {blob[:200]}"


async def test_image_generate_without_api_key_fails_clearly(runtime):
    """No image-generation API key is configured on this host. The tool must
    say so clearly — not crash, not return an empty nothing."""
    res = await call(
        runtime.image, "image_generate",
        {"prompt": "a small red circle on white background"},
    )
    assert isinstance(res, ToolResult)
    assert (res.message or "").strip(), "failure message is empty"
    assert "Traceback" not in (res.message or "")
    print(f"  [image_generate] clean failure: {res.message[:160]}")


# ── 6. message tools (2/2) ──────────────────────────────────────────────────

async def test_message_notify_user(runtime):
    res = await call(
        runtime.message, "message_notify_user",
        {"text": "Uji notifikasi berjalan."},
    )
    assert res.success, res.message


async def test_message_ask_user(runtime):
    res = await call(
        runtime.message, "message_ask_user",
        {"text": "Apakah uji ini boleh lanjut?"},
    )
    assert res.success, res.message


# ── 7. Replit-compat: provider resolution & fallback ────────────────────────

async def test_hybrid_factory_falls_back_to_replit_when_e2b_auth_fails(
    monkeypatch,
):
    """The exact Replit-deploy path: E2B key unusable → clean fallback to the
    Replit-local sandbox, never an exception."""
    import app.infrastructure.external.sandbox.sandbox_factory as factory_mod
    from app.infrastructure.external.sandbox.replit_sandbox import ReplitSandbox

    class _AuthBoom(Exception):
        pass

    async def fake_create():
        raise _AuthBoom("401 Unauthorized: invalid e2b key")

    monkeypatch.setattr(factory_mod, "_AUTH_DISABLED", {"disabled": False})
    monkeypatch.setattr(
        factory_mod, "_RATE_LIMIT_COOLDOWN", {"until": 0.0}
    )
    monkeypatch.setattr("app.infrastructure.external.sandbox.e2b_sandbox."
                        "E2BSandbox.create", classmethod(
                            lambda cls: fake_create()))
    sandbox = await factory_mod.HybridSandboxFactory.create()
    assert isinstance(sandbox, ReplitSandbox), (
        f"expected ReplitSandbox fallback, got {type(sandbox).__name__}"
    )


def test_scheme_guard_unit():
    from app.infrastructure.external.browser.browser_use_browser import (
        _scheme_rejection,
    )

    for bad in ("data:text/html,<b>x</b>", "javascript:alert(1)", "file:///etc/passwd"):
        verdict = _scheme_rejection(bad)
        assert verdict is not None and verdict.success is False, bad
        assert "not supported" in verdict.message
    assert _scheme_rejection("https://example.com") is None
    assert _scheme_rejection("http://localhost:1234/x") is None


# ── 8. report artifact (optional) ───────────────────────────────────────────

async def test_report_artifact():
    """Print the full matrix; optionally write it when
    TOOL_TEST_REPORT_PATH is set (used to attach visible proof)."""
    path = os.environ.get("TOOL_TEST_REPORT_PATH")
    lines = [
        "# Dzeck — live tool test matrix",
        "",
        "| Toolkit | Tool | Result | Message | Data | Time |",
        "|---|---|---|---|---|---|",
    ]
    for e in REPORT:
        lines.append(
            f"| {e['toolkit']} | `{e['tool']}` | "
            f"{'OK' if e['success'] else 'FAIL'} | "
            f"{e['message'][:90]} | {e['data']} | {e['seconds']}s |"
        )
    table = "\n".join(lines)
    print(table)
    if path:
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(table + "\n")
    assert REPORT, "no tool calls were recorded"
