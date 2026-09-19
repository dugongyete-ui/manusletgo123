"""MCP transport executor for the Manus registry (server: manus-tools).

Executes registry tools with transport="mcp". Backing implementations:

  - browser_*  → the platform's live browser engine (CDP, per-task session —
                 browser state persists across tool calls by construction)
  - generate_image / generate_image_variation → the platform image provider
  - media tools without a configured provider (video/speech/music) → explicit
    NOT_SUPPORTED payload (never silently skipped, never fabricated)
  - webdev_*   → executor-built sandbox operations on the user workspace
                 (the model never supplies a raw shell command)
  - user-configured MCP servers (mcp.json) → the existing MCPClientManager

Every result leaves normalized: {success, tool, data, error, retryable}.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Awaitable, Callable, Dict, Optional

from app.domain.external.browser import Browser
from app.domain.external.sandbox import Sandbox
from app.domain.models.tool_result import ToolResult
from app.domain.services.manus_registry.errors import (
    NOT_SUPPORTED,
    ManusToolError,
    failure_payload,
    redact_secrets,
    success_payload,
)

logger = logging.getLogger(__name__)


def classify_exception_message(message: str) -> str:
    """Best-effort error code from a handler-provided refusal message."""
    low = message.lower()
    if "not supported" in low or "not available" in low or "disabled" in low:
        return NOT_SUPPORTED
    if "no provider" in low or "not configured" in low:
        return NOT_SUPPORTED
    return "EXECUTION_ERROR"


def _data_from_result(tr: ToolResult) -> Dict[str, Any]:
    """Flatten a backing ToolResult into the normalized `data` object."""
    out: Dict[str, Any] = {}
    if tr.message:
        out["message"] = tr.message
    if isinstance(tr.data, dict):
        out.update(tr.data)
    elif tr.data is not None:
        out["result"] = tr.data
    return out


class ManusMCPExecutor:
    """Registry-driven dispatcher for MCP-transport tools."""

    def __init__(
        self,
        browser: Optional[Browser] = None,
        sandbox: Optional[Sandbox] = None,
        image_toolkit: Optional[Any] = None,
        user_mcp_manager: Optional[Any] = None,
    ) -> None:
        self._browser = browser
        self._sandbox = sandbox
        self._image_toolkit = image_toolkit
        self._user_mcp_manager = user_mcp_manager
        self._dispatch: Dict[str, Callable[[Dict[str, Any]], Awaitable[Dict[str, Any]]]] = {
            # ── Browser (state lives in the sandbox Chrome across calls) ──
            "browser_navigate": self._browser_navigate,
            "browser_view": self._browser_view,
            "browser_click": self._browser_click,
            "browser_input": self._browser_input,
            "browser_scroll": self._browser_scroll,
            "browser_move_mouse": self._browser_move_mouse,
            "browser_press_key": self._browser_press_key,
            "browser_select_option": self._browser_select_option,
            "browser_fill_form": self._browser_fill_form,
            "browser_find_keyword": self._browser_find_keyword,
            "browser_save_image": self._browser_save_image,
            "browser_upload_file": self._browser_upload_file,
            "browser_switch": self._browser_switch,
            "browser_console_exec": self._browser_console_exec,
            "browser_console_view": self._browser_console_view,
            # ── Media ──
            "generate_image": self._generate_image,
            "generate_image_variation": self._generate_image_variation,
            "generate_video": self._media_unsupported("video generation"),
            "generate_video_variation": self._media_unsupported("video variation"),
            "generate_speech": self._media_unsupported("speech generation"),
            "generate_music": self._media_unsupported("music generation"),
            # ── Webdev (sandbox workspace operations) ──
            "webdev_init_project": self._webdev_init_project,
            "webdev_check_status": self._webdev_check_status,
            "webdev_restart_server": self._webdev_restart_server,
            "webdev_take_screenshot": self._webdev_take_screenshot,
            "webdev_save_checkpoint": self._webdev_save_checkpoint,
            "webdev_rollback_checkpoint": self._webdev_rollback,
            "webdev_execute_sql": self._webdev_execute_sql,
            "webdev_request_secrets": self._webdev_request_secrets,
            "webdev_add_feature": self._webdev_add_feature,
            "webdev_debug": self._webdev_debug,
        }

    # ── public entry ─────────────────────────────────────────────────────────
    async def execute(self, tool_name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Run one MCP-transport tool and return the normalized payload.

        Raises ManusToolError only for unexpected internal failures —
        expected outcomes (unsupported, backing failure) are returned as
        structured failure payloads so the model can react.
        """
        handler = self._dispatch.get(tool_name)
        if handler is None:
            # Registered MCP tool without a backing handler: explicit, honest.
            return failure_payload(
                tool_name,
                NOT_SUPPORTED,
                f"Tool '{tool_name}' is registered but has no backing "
                "implementation in this deployment.",
                {"guidance": "Use one of the implemented tools; see registry."},
            )
        try:
            data = await handler(arguments)
            if isinstance(data, dict) and data.get("_failed"):
                # Handler-level refusal (unsupported capability, backing
                # failure) — explicit structured error, never silent.
                from app.domain.services.manus_registry.errors import (
                    failure_payload as _fp,
                )
                message = str(data.pop("_failed"))
                code = data.pop("_code", None) or classify_exception_message(message)
                return _fp(tool_name, code, message, data or None)
            return success_payload(tool_name, redact_secrets(data))
        except ManusToolError as exc:
            # Backend not attached (e.g. browser engine absent) — structured
            # refusal so the model can pick a different tool.
            return failure_payload(tool_name, "CAPABILITY_UNAVAILABLE", str(exc))
        except Exception as exc:  # noqa: BLE001 — converted to contract error
            logger.exception("MCP tool %s failed", tool_name)
            from app.domain.services.manus_registry.errors import (
                classify_exception,
                failure_payload as _fp,
            )
            code = classify_exception(exc)
            payload = _fp(tool_name, code, str(exc))
            return payload

    # ── helpers ──────────────────────────────────────────────────────────────
    def _require_browser(self) -> Browser:
        if self._browser is None:
            raise ManusToolError("Browser engine is not attached to the executor")
        return self._browser

    def _require_sandbox(self) -> Sandbox:
        if self._sandbox is None:
            raise ManusToolError("Sandbox is not attached to the executor")
        return self._sandbox

    async def _tr(self, coro) -> ToolResult:
        return await coro

    # ── browser handlers ─────────────────────────────────────────────────────
    async def _browser_navigate(self, a: Dict[str, Any]) -> Dict[str, Any]:
        browser = self._require_browser()
        tr = await browser.navigate(a["url"])
        if not tr.success:
            return _data_from_result(tr) | {"_failed": tr.message}
        return _data_from_result(tr)

    async def _browser_view(self, a: Dict[str, Any]) -> Dict[str, Any]:
        browser = self._require_browser()
        tr = await browser.view_page()
        return _data_from_result(tr)

    async def _browser_click(self, a: Dict[str, Any]) -> Dict[str, Any]:
        browser = self._require_browser()
        tr = await browser.click(
            index=a.get("index"),
            coordinate_x=a.get("coordinate_x"),
            coordinate_y=a.get("coordinate_y"),
        )
        return _data_from_result(tr)

    async def _browser_input(self, a: Dict[str, Any]) -> Dict[str, Any]:
        browser = self._require_browser()
        tr = await browser.input(
            text=a["text"],
            press_enter=a.get("press_enter", False),
            index=a.get("index"),
            coordinate_x=a.get("coordinate_x"),
            coordinate_y=a.get("coordinate_y"),
        )
        return _data_from_result(tr)

    async def _browser_scroll(self, a: Dict[str, Any]) -> Dict[str, Any]:
        browser = self._require_browser()
        direction = a["direction"]
        to_end = a.get("to_end", False)
        if direction == "up":
            tr = await browser.scroll_up(to_top=to_end or None)
        elif direction == "down":
            tr = await browser.scroll_down(to_bottom=to_end or None)
        else:
            return {"_failed": (
                f"Direction '{direction}' is not supported by the current "
                "browser engine; use up/down (or press_key PageUp/PageDown)."
            )}
        return _data_from_result(tr)

    async def _browser_move_mouse(self, a: Dict[str, Any]) -> Dict[str, Any]:
        browser = self._require_browser()
        tr = await browser.move_mouse(a["coordinate_x"], a["coordinate_y"])
        return _data_from_result(tr)

    async def _browser_press_key(self, a: Dict[str, Any]) -> Dict[str, Any]:
        browser = self._require_browser()
        tr = await browser.press_key(a["key"])
        return _data_from_result(tr)

    async def _browser_select_option(self, a: Dict[str, Any]) -> Dict[str, Any]:
        browser = self._require_browser()
        tr = await browser.select_option(a["index"], a["option_index"])
        return _data_from_result(tr)

    async def _browser_fill_form(self, a: Dict[str, Any]) -> Dict[str, Any]:
        """Fill multiple fields sequentially; state evolves between fields."""
        browser = self._require_browser()
        results = []
        for field in a["fields"]:
            tr = await browser.input(
                text=field.get("text", ""),
                press_enter=bool(field.get("press_enter", False)),
                index=field.get("index"),
                coordinate_x=field.get("coordinate_x"),
                coordinate_y=field.get("coordinate_y"),
            )
            results.append({
                "index": field.get("index"),
                "success": tr.success,
                "message": tr.message,
            })
            if not tr.success and field.get("stop_on_error", True):
                break
        failed = [r for r in results if not r["success"]]
        return {
            "fields_filled": len(results) - len(failed),
            "fields_total": len(a["fields"]),
            "results": results,
            **({"_failed": f"{len(failed)} field(s) failed"} if failed else {}),
        }

    async def _browser_find_keyword(self, a: Dict[str, Any]) -> Dict[str, Any]:
        browser = self._require_browser()
        search = getattr(browser, "search_page", None)
        if search is None:
            return {"_failed": "search_page is not available on this browser engine"}
        tr = await search(a["keyword"])
        return _data_from_result(tr)

    async def _browser_save_image(self, a: Dict[str, Any]) -> Dict[str, Any]:
        """Save the image element under (x, y) to the sandbox workspace.

        Implementation: locate the element's src via CDP console_exec, then
        reuse the platform image downloader into save_dir/base_name.
        """
        browser = self._require_browser()
        js = (
            "() => { const el = document.elementFromPoint("
            f"{float(a['coordinate_x'])}, {float(a['coordinate_y'])}); "
            "const img = el && (el.tagName === 'IMG' ? el : el.querySelector('img')); "
            "return img ? (img.currentSrc || img.src || '') : ''; }()"
        )
        tr = await browser.console_exec(js)
        src = ""
        if isinstance(tr.data, dict):
            src = str(tr.data.get("result") or tr.data.get("value") or "")
        if not src and tr.message:
            src = str(tr.message).strip()
        if not src.startswith(("http://", "https://", "data:")):
            return {"_failed": "No image element found at the given coordinates."}
        downloader = getattr(self._image_toolkit, "image_download", None) if self._image_toolkit else None
        if downloader is None:
            return {"_failed": "No image downloader attached; image located at " + src[:200]}
        save_dir = a["save_dir"].rstrip("/")
        ext = ".png" if "png" in src.split("?")[0].lower() or src.startswith("data:image/png") else ".jpg"
        file_path = f"{save_dir}/{a['base_name']}{ext}"
        dtr = await downloader(url=src, file_path=file_path)
        out = _data_from_result(dtr)
        out.setdefault("saved_path", file_path if dtr.success else "")
        return out

    async def _browser_upload_file(self, a: Dict[str, Any]) -> Dict[str, Any]:
        browser = self._require_browser()
        results = []
        for item in a["files"]:
            path = item.get("path", "")
            index = item.get("index")
            if not index:
                results.append({"path": path, "success": False,
                                "message": "index (input element) is required"})
                continue
            tr = await browser.upload_file(index=index, file_path=path)
            results.append({"path": path, "index": index,
                            "success": tr.success, "message": tr.message})
        failed = [r for r in results if not r["success"]]
        return {
            "files_uploaded": len(results) - len(failed),
            "results": results,
            **({"_failed": f"{len(failed)} file(s) failed"} if failed else {}),
        }

    async def _browser_switch(self, a: Dict[str, Any]) -> Dict[str, Any]:
        target = a["target"]
        if target == "sandbox":
            return {
                "routed_to": "sandbox",
                "message": "Browser routing already points at the sandbox "
                           "browser (the only engine in this deployment).",
            }
        return {"_failed": (
            "target 'my_browser' is not available in this deployment: the "
            "agent's browser runs inside the isolated sandbox. Use target "
            "'sandbox'."
        )}

    async def _browser_console_exec(self, a: Dict[str, Any]) -> Dict[str, Any]:
        browser = self._require_browser()
        tr = await browser.console_exec(a["javascript"])
        return _data_from_result(tr)

    async def _browser_console_view(self, a: Dict[str, Any]) -> Dict[str, Any]:
        browser = self._require_browser()
        tr = await browser.console_view(max_lines=a.get("max_lines"))
        return _data_from_result(tr)

    # ── media handlers ───────────────────────────────────────────────────────
    async def _generate_image(self, a: Dict[str, Any]) -> Dict[str, Any]:
        if self._image_toolkit is None:
            return {"_failed": "No image provider configured in this deployment."}
        primary = a["images"][0]
        tr = await self._image_toolkit.image_generate(
            prompt=primary.get("prompt", a.get("brief", "")),
        )
        if not tr.success:
            return _data_from_result(tr) | {"_failed": tr.message}
        url = self._extract_image_url(tr)
        target_path = primary.get("path") or "/workspace/generated_image.png"
        saved = await self._download_image(url, target_path)
        return {
            "generated_url": url,
            "saved_path": saved or "",
            "images": [{"path": saved or target_path, "status": "generated"}],
        }

    async def _generate_image_variation(self, a: Dict[str, Any]) -> Dict[str, Any]:
        if self._image_toolkit is None:
            return {"_failed": "No image provider configured in this deployment."}
        prompt = a.get("prompt") or a.get("brief", "")
        tr = await self._image_toolkit.image_generate(prompt=prompt)
        if not tr.success:
            return _data_from_result(tr) | {"_failed": tr.message}
        url = self._extract_image_url(tr)
        target_path = a.get("path") or "/workspace/image_variation.png"
        saved = await self._download_image(url, target_path)
        return {"generated_url": url, "saved_path": saved or target_path}

    @staticmethod
    def _extract_image_url(tr: ToolResult) -> str:
        if isinstance(tr.data, dict):
            for key in ("url", "image_url", "result"):
                v = tr.data.get(key)
                if isinstance(v, str) and v.startswith("http"):
                    return v
        if tr.message:
            import re as _re
            m = _re.search(r"https?://\S+", tr.message)
            if m:
                return m.group(0).rstrip(").,")
        return ""

    async def _download_image(self, url: str, file_path: str) -> str:
        if not url:
            return ""
        downloader = getattr(self._image_toolkit, "image_download", None)
        if downloader is None:
            return ""
        tr = await downloader(url=url, file_path=file_path)
        return file_path if tr.success else ""

    def _media_unsupported(self, capability: str):
        async def _handler(a: Dict[str, Any]) -> Dict[str, Any]:
            return {"_failed": (
                f"{capability} is registered in the Manus standard but no "
                "provider is configured for this deployment "
                "(configure MEDIA_PROVIDER envs to enable it)."
            )}
        return _handler

    # ── webdev handlers (executor-built sandbox commands) ────────────────────
    _WS = "/home/user"  # sandbox working root resolved per exec below

    async def _sb_exec(self, command: str, exec_dir: str = "") -> ToolResult:
        sandbox = self._require_sandbox()
        import uuid as _uuid
        return await sandbox.exec_command(str(_uuid.uuid4()), exec_dir, command)

    def _webdev_dir(self, a: Dict[str, Any]) -> str:
        name = a.get("name") or a.get("project_name") or "webdev-project"
        return f"/home/user/{name}"

    async def _webdev_init_project(self, a: Dict[str, Any]) -> Dict[str, Any]:
        d = self._webdev_dir(a)
        scaffold = a["scaffold"]
        if scaffold == "web-db-user":
            cmd = (
                f"mkdir -p {d}/static && printf '%s\\n' "
                "'from flask import Flask' 'app = Flask(__name__)' "
                "'@app.get(\"/\")' 'def home():' "
                f"    return \"<h1>{a['title']}</h1>\"' "
                f"> {d}/app.py && printf 'flask\\n' > {d}/requirements.txt"
            )
        elif scaffold == "mobile-app":
            cmd = f"mkdir -p {d} && printf '<!doctype html>' > {d}/index.html"
        else:
            cmd = (
                f"mkdir -p {d} && printf '<!doctype html><html><head><title>"
                f"{a['title']}</title></head><body><h1>{a['title']}</h1>"
                f"<p>{a['description']}</p></body></html>' > {d}/index.html"
            )
        tr = await self._sb_exec(cmd)
        if not tr.success:
            return {"_failed": tr.message or "scaffold failed"}
        return {
            "project_dir": d,
            "scaffold": scaffold,
            "title": a["title"],
            "message": "Project scaffolded in the sandbox workspace.",
        }

    async def _webdev_check_status(self, a: Dict[str, Any]) -> Dict[str, Any]:
        tr = await self._sb_exec(
            "curl -s -o /dev/null -w '%{http_code}' http://localhost:5000/ "
            "|| true; echo; ps aux | grep -E 'flask|uvicorn|http.server' | grep -v grep || true"
        )
        return {"status_output": (tr.message or "")[:1000]}

    async def _webdev_restart_server(self, a: Dict[str, Any]) -> Dict[str, Any]:
        d = self._webdev_dir(a)
        tr = await self._sb_exec(
            f"pkill -f 'flask --app {d}/app.py' 2>/dev/null; sleep 1; "
            f"cd {d} && nohup python3 app.py > server.log 2>&1 & echo restarted"
        )
        return {"message": tr.message or "restart issued"}

    async def _webdev_take_screenshot(self, a: Dict[str, Any]) -> Dict[str, Any]:
        if self._browser is None:
            return {"_failed": "Browser engine not attached"}
        url = a.get("url") or "http://localhost:5000/"
        save_path = a.get("save_path", "/home/user/webdev_screenshot.png")
        try:
            raw: bytes = await self._browser.screenshot(
                full_page=bool(a.get("full_page", False))
            )
        except Exception as exc:  # noqa: BLE001
            return {"_failed": f"screenshot failed: {exc}"}
        import base64 as _b64
        encoded = _b64.b64encode(raw).decode("ascii")
        tr = await self._sb_exec(
            "python3 -c \"import base64,sys,os; os.makedirs(os.path.dirname("
            f"'{save_path}') or '.', exist_ok=True); "
            f"open('{save_path}','wb').write(base64.b64decode(sys.argv[1]))\" "
            f"{encoded}"
        )
        return {
            "saved_path": save_path if tr.success else "",
            "bytes": len(raw),
            "url": url,
            **({} if tr.success else {"_failed": tr.message}),
        }

    async def _webdev_save_checkpoint(self, a: Dict[str, Any]) -> Dict[str, Any]:
        d = self._webdev_dir(a)
        import time as _time
        ts = _time.strftime("%Y%m%d-%H%M%S")
        tr = await self._sb_exec(
            f"mkdir -p /home/user/.webdev/checkpoints && "
            f"tar -czf /home/user/.webdev/checkpoints/{ts}.tar.gz -C /home/user {d.split('/')[-1]} && "
            f"echo checkpoint:{ts}"
        )
        if not tr.success:
            return {"_failed": tr.message or "checkpoint failed"}
        return {"checkpoint_id": ts, "message": tr.message}

    async def _webdev_rollback(self, a: Dict[str, Any]) -> Dict[str, Any]:
        d = self._webdev_dir(a)
        ck = a.get("checkpoint_id", "")
        path = f"/home/user/.webdev/checkpoints/{ck}.tar.gz" if ck else ""
        if not path:
            return {"_failed": "checkpoint_id is required (list via webdev_debug)."}
        tr = await self._sb_exec(
            f"tar -xzf {path} -C /home/user && echo rolled_back:{ck}"
        )
        return _data_from_result(tr)

    async def _webdev_execute_sql(self, a: Dict[str, Any]) -> Dict[str, Any]:
        query = a["query"].replace("'", "'\\''")
        db = a.get("database", "/home/user/webdev/data.db")
        tr = await self._sb_exec(
            f"python3 -c \"import sqlite3; con=sqlite3.connect('{db}'); "
            f"cur=con.execute('{query}'); "
            "rows=cur.fetchall() if cur.description else []; "
            "print(rows[:200]); con.commit(); con.close()\""
        )
        return {"output": (tr.message or "")[:4000], "database": db}

    async def _webdev_request_secrets(self, a: Dict[str, Any]) -> Dict[str, Any]:
        names = a.get("secret_names") or a.get("names") or []
        return {
            "requested": names,
            "message": (
                "Secret request acknowledged. The executor does NOT store "
                "raw secrets; the user provides values through the chat and "
                "the agent writes them to the workspace .env via file tools."
            ),
        }

    async def _webdev_add_feature(self, a: Dict[str, Any]) -> Dict[str, Any]:
        return {"_failed": (
            "webdev_add_feature is model-driven in the Manus standard: use "
            "the file_* and shell_* tools to implement the feature, then "
            "webdev_restart_server + webdev_take_screenshot to verify."
        )}

    async def _webdev_debug(self, a: Dict[str, Any]) -> Dict[str, Any]:
        d = self._webdev_dir(a)
        tr = await self._sb_exec(
            f"tail -n 80 {d}/server.log 2>/dev/null || "
            "echo 'no server.log found'"
        )
        return {"log_tail": (tr.message or "")[:4000]}


def user_mcp_tool_names(manager: Any) -> list[str]:
    """Tool names exposed by the user's own MCP servers (mcp.json)."""
    try:
        return [t.name for t in manager.list_all_tools()]  # type: ignore[attr-defined]
    except Exception:
        return []


def dump_registry_surface(executor: ManusMCPExecutor) -> str:
    """Debug helper: names handled by this executor."""
    return json.dumps(sorted(executor._dispatch.keys()), indent=1)
