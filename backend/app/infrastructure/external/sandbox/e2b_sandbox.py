"""E2B cloud sandbox — per-user fully isolated execution environment.

Each Dzeck session backed by E2B gets its own Firecracker microVM:
its own filesystem, its own shell, its own Chromium instance (own cookies and
profile). Nothing is shared with other users, so cross-account leakage of
files, shell state, or browser sessions is impossible by construction.

Key engineering notes (all verified empirically against e2b SDK 2.x):

1. V8 renderer OOM fix — E2B microVMs ship with a small amount of RAM and the
   default kernel overcommit policy. V8's pointer-compression cage wants a
   4 GB *virtual* reservation; without overcommit the reservation fails and
   every Chromium renderer dies instantly:
       "V8 process OOM (Failed to reserve virtual memory for CodeRange)"
   The renderer being dead is why *browser-process* CDP commands
   (Browser.getVersion / Target.getTargets / Page.navigate) responded while
   every *renderer* command (Page.enable / Runtime.evaluate) hung forever.
   Fix: `sudo sysctl -w vm.overcommit_memory=1` on every (re)boot of the VM.

2. CDP over the public proxy — Chrome's DevTools HTTP handler rejects requests
   whose Host header is not localhost/an IP (DNS-rebinding protection), so the
   E2B edge proxy domain gets a 500. A tiny nginx site inside the VM rewrites
   Host to "localhost" and proxies to 127.0.0.1:9222. Chrome builds the
   webSocketDebuggerUrl from the Host header (ws://localhost/...), so we fetch
   /json/version through the proxy ourselves and re-bind the returned path to
   the public `wss://{port-host}` URL before handing it to playwright.

3. Pause/resume — an idle sandbox is paused after `e2b_sandbox_timeout`
   seconds. Disk state (apt packages, files) survives; processes and kernel
   sysctls do NOT. `ensure_sandbox()` is therefore a cheap idempotent
   bootstrap that re-applies the sysctl, re-launches nginx + Chromium and only
   apt-installs once per sandbox lifetime (flag file on disk).

4. Fallback contract — every public method may raise; the
   HybridSandboxFactory catches failures (quota/auth/network) and transparently
   falls back to the shared Replit sandbox so user tasks never crash.
"""

import asyncio
import io
import logging
import re
from typing import Optional, BinaryIO

import httpx

from app.core.config import get_settings
from app.domain.external.browser import Browser
from app.domain.models.tool_result import ToolResult
from app.infrastructure.external.browser.browser_use_browser import BrowserUseBrowser
from app.infrastructure.external.browser.playwright_browser import PlaywrightBrowser

logger = logging.getLogger(__name__)

# Internal ports inside the E2B VM
_CHROME_DEBUG_PORT = 9222
_CDP_PROXY_PORT = 9223  # nginx Host-rewrite proxy → chrome

_SETUP_FLAG = "/home/user/.dzeck_env_ready"

_ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[a-zA-Z]|\x1b\][^\x07]*\x07|\x1b\[()][0-9;]*")

_NGINX_CDP_CONF = """server {{
    listen {_port};
    location / {{
        proxy_pass http://127.0.0.1:{_chrome_port};
        proxy_set_header Host localhost;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_read_timeout 3600s;
        proxy_send_timeout 3600s;
    }}
}}
"""


class E2BSandbox:
    """Sandbox protocol implementation backed by one E2B microVM.

    `shared = False` marks this sandbox as already user-isolated so the domain
    service skips the UserScopedSandbox wrapper (which only makes sense around
    the shared Replit sandbox).
    """

    shared = False

    # Cache wrappers by raw sandbox id so repeated get() calls reuse the same
    # shell-session bookkeeping within a backend process.
    _registry: dict[str, "E2BSandbox"] = {}
    _registry_lock = asyncio.Lock()

    def __init__(self, sbx) -> None:
        self._sbx = sbx
        self._raw_id = sbx.sandbox_id
        self._id = f"e2b:{self._raw_id}"
        self._bootstrap_lock = asyncio.Lock()
        self._bootstrapped = False
        # session_id -> {handle, started_at}
        self._shell_sessions: dict[str, dict] = {}
        self._http = httpx.AsyncClient(timeout=30)

    # ------------------------------------------------------------------
    # Factory / lifecycle
    # ------------------------------------------------------------------

    @classmethod
    def _api_key(cls) -> Optional[str]:
        return get_settings().e2b_api_key

    @classmethod
    async def create(cls) -> "E2BSandbox":
        from e2b import AsyncSandbox

        settings = get_settings()
        timeout = max(60, int(settings.e2b_sandbox_timeout or 3600))
        sbx = await AsyncSandbox.create(
            api_key=cls._api_key(), timeout=timeout
        )
        wrapper = cls(sbx)
        cls._registry[sbx.sandbox_id] = wrapper
        logger.info("E2BSandbox created: %s", wrapper.id)
        await wrapper.ensure_sandbox()
        return wrapper

    @classmethod
    async def get(cls, id: str) -> "E2BSandbox":
        """Reconnect to an existing (possibly paused) E2B sandbox by id.

        `id` may carry the "e2b:" prefix used in session.sandbox_id. Raises on
        failure — the caller (HybridSandboxFactory) falls back gracefully.
        """
        from e2b import AsyncSandbox

        raw = id.removeprefix("e2b:")
        async with cls._registry_lock:
            cached = cls._registry.get(raw)
            if cached is not None:
                return cached
            sbx = await AsyncSandbox.connect(raw, api_key=cls._api_key())
            wrapper = cls(sbx)
            cls._registry[raw] = wrapper
        logger.info("E2BSandbox reconnected: %s", wrapper.id)
        await wrapper.ensure_sandbox()
        return wrapper

    async def destroy(self) -> bool:
        try:
            await self._sbx.kill()
        except Exception as exc:
            logger.warning("E2BSandbox.destroy(%s) failed: %s", self.id, exc)
        self._registry.pop(self._raw_id, None)
        return True

    # ------------------------------------------------------------------
    # Idempotent bootstrap (safe after every pause/resume)
    # ------------------------------------------------------------------

    async def ensure_sandbox(self) -> None:
        async with self._bootstrap_lock:
            if self._bootstrapped:
                # keepalive only — cheap
                try:
                    await self._sbx.set_timeout(
                        max(60, int(get_settings().e2b_sandbox_timeout or 3600))
                    )
                except Exception:
                    pass
                return
            try:
                await self._bootstrap()
                self._bootstrapped = True
            except Exception as exc:
                raise RuntimeError(f"E2B sandbox bootstrap failed: {exc}") from exc

    async def _cmd(self, command: str, timeout: float = 60) -> str:
        """Run a quick command, returning stdout (empty string on failure)."""
        try:
            result = await self._sbx.commands.run(command, timeout=timeout)
            return result.stdout or ""
        except Exception as exc:
            logger.debug("E2B cmd failed (%s): %s", command[:60], exc)
            return ""

    async def _bootstrap(self) -> None:
        settings = get_settings()
        try:
            await self._sbx.set_timeout(
                max(60, int(settings.e2b_sandbox_timeout or 3600))
            )
        except Exception:
            pass

        # 1. THE V8 fix — kernel state resets on resume, apply every time.
        await self._cmd("sudo sysctl -w vm.overcommit_memory=1")
        await self._cmd("sudo sysctl -w vm.max_map_count=1048576")

        # 2. One-time package install (survives pause via disk flag).
        flag = await self._cmd(f"test -f {_SETUP_FLAG} && echo YES || echo NO")
        if "YES" not in flag:
            logger.info("E2B: installing chromium + nginx (first boot of %s)…", self.id)
            install = await self._cmd(
                "sudo apt-get update -qq && sudo apt-get install -y -qq "
                "chromium nginx-light zip unzip >/dev/null 2>&1; echo OK",
                timeout=420,
            )
            if "OK" not in install:
                raise RuntimeError("apt install chromium/nginx failed")
            await self._cmd(f"echo ready > {_SETUP_FLAG}")

        # 3. Chromium up? (processes die on pause — relaunch when needed)
        chrome_up = await self._cmd(
            f"curl -s --max-time 3 http://127.0.0.1:{_CHROME_DEBUG_PORT}/json/version >/dev/null && echo UP || echo DOWN"
        )
        if "UP" not in chrome_up:
            await self._cmd(
                "nohup chromium --headless=new --no-sandbox --disable-gpu "
                "--disable-dev-shm-usage --renderer-process-limit=4 "
                f"--remote-debugging-port={_CHROME_DEBUG_PORT} "
                "--remote-debugging-address=127.0.0.1 --remote-allow-origins=* "
                "--user-data-dir=/home/user/chrome-profile about:blank "
                ">/tmp/chrome.log 2>&1 & echo LAUNCHED"
            )
            # wait for CDP to answer (bounded)
            for _ in range(20):
                up = await self._cmd(
                    f"curl -s --max-time 2 http://127.0.0.1:{_CHROME_DEBUG_PORT}/json/version >/dev/null && echo UP || echo DOWN"
                )
                if "UP" in up:
                    break
                await asyncio.sleep(1)
            else:
                raise RuntimeError("Chromium CDP did not come up inside E2B VM")

        # 4. nginx Host-rewrite proxy up?
        proxy_up = await self._cmd(
            f"curl -s --max-time 3 http://127.0.0.1:{_CDP_PROXY_PORT}/json/version >/dev/null && echo UP || echo DOWN"
        )
        if "UP" not in proxy_up:
            conf = _NGINX_CDP_CONF.format(
                _port=_CDP_PROXY_PORT, _chrome_port=_CHROME_DEBUG_PORT
            )
            await self._sbx.files.write("/tmp/cdp_proxy.conf", conf)
            await self._cmd(
                "sudo mv /tmp/cdp_proxy.conf /etc/nginx/sites-enabled/cdp_proxy "
                "&& sudo nginx -t >/dev/null 2>&1 "
                "&& (sudo nginx 2>/dev/null || sudo service nginx reload) && sleep 1; echo NGINX"
            )
            for _ in range(10):
                up = await self._cmd(
                    f"curl -s --max-time 2 http://127.0.0.1:{_CDP_PROXY_PORT}/json/version >/dev/null && echo UP || echo DOWN"
                )
                if "UP" in up:
                    break
                await asyncio.sleep(1)
            else:
                raise RuntimeError("nginx CDP proxy did not come up inside E2B VM")

        # 5. Working dirs for the agent.
        await self._cmd("mkdir -p /home/user/upload && chmod 700 /home/user")

        logger.info("E2B sandbox ready: %s", self.id)

    # ------------------------------------------------------------------
    # Browser (CDP over public wss proxy)
    # ------------------------------------------------------------------

    async def _cdp_ws_url(self) -> str:
        host = self._sbx.get_host(_CDP_PROXY_PORT)
        resp = await self._http.get(f"https://{host}/json/version", timeout=20)
        resp.raise_for_status()
        ver = resp.json()
        ws_path = ver["webSocketDebuggerUrl"].split("/devtools", 1)[1]
        return f"wss://{host}/devtools{ws_path}"

    async def get_browser(self) -> Browser:
        settings = get_settings()
        engine = (settings.browser_engine or "browser_use").lower().strip()
        url = await self._cdp_ws_url()
        if engine == "browser_use":
            logger.info("E2B: BrowserUseBrowser via CDP proxy (%s)", self.id)
            return BrowserUseBrowser(url)
        logger.info("E2B: PlaywrightBrowser via CDP proxy (%s)", self.id)
        return PlaywrightBrowser(url)

    # ------------------------------------------------------------------
    # Shell sessions (mirror the Replit sandbox HTTP API semantics)
    # ------------------------------------------------------------------

    def _ansi_clean(self, text: str) -> str:
        return _ANSI_RE.sub("", text or "")

    async def exec_command(
        self,
        session_id: str,
        exec_dir: str,
        command: str,
    ) -> ToolResult:
        await self.ensure_sandbox()
        cwd = exec_dir or "/home/user"
        try:
            # kill any previous process on this session (Replit semantics:
            # re-exec on the same id replaces the process and clears output)
            old = self._shell_sessions.pop(session_id, None)
            if old and old.get("handle") is not None:
                try:
                    await old["handle"].kill()
                except Exception:
                    pass
            handle = await self._sbx.commands.run(
                command, background=True, cwd=cwd
            )
        except Exception as exc:
            # cwd may not exist (agent guessed a path) — retry in home
            try:
                handle = await self._sbx.commands.run(
                    command, background=True, cwd="/home/user"
                )
            except Exception as exc2:
                return ToolResult(
                    success=False,
                    message=f"Command execution failed: {exc2 or exc}",
                )
        self._shell_sessions[session_id] = {"handle": handle}

        # Give quick commands up to 5s to finish (mirrors the Replit API that
        # waits ~5s and returns completed output directly).
        try:
            result = await asyncio.wait_for(handle.wait(), timeout=5)
            output = self._ansi_clean(
                (result.stdout or "") + (("\n" + result.stderr) if result.stderr else "")
            )
            return ToolResult(
                success=True,
                message="Command execution completed",
                data={
                    "status": "completed",
                    "returncode": result.exit_code,
                    "output": output,
                },
            )
        except asyncio.TimeoutError:
            return ToolResult(
                success=True,
                message="Command started",
                data={"status": "running", "returncode": None, "output": None},
            )
        except Exception as exc:
            # Non-zero exit etc. — command "completed" with a return code.
            exit_code = getattr(exc, "exit_code", None)
            stdout = getattr(exc, "stdout", "") or ""
            stderr = getattr(exc, "stderr", "") or ""
            output = self._ansi_clean(stdout + (("\n" + stderr) if stderr else ""))
            return ToolResult(
                success=True,
                message="Command execution completed",
                data={
                    "status": "completed",
                    "returncode": exit_code if exit_code is not None else 1,
                    "output": output,
                },
            )

    def _session(self, session_id: str):
        entry = self._shell_sessions.get(session_id)
        return (entry or {}).get("handle")

    async def view_shell(self, session_id: str, console: bool = False) -> ToolResult:
        handle = self._session(session_id)
        if handle is None:
            return ToolResult(
                success=False,
                message=f"No active shell session: {session_id}",
                data={"status": "not_found", "output": ""},
            )
        try:
            stdout = handle.stdout or ""
            stderr = handle.stderr or ""
        except Exception:
            stdout = stderr = ""
        output = self._ansi_clean(
            stdout + (("\n" + stderr) if stderr else "")
        )
        return ToolResult(
            success=True,
            message="Shell session output",
            data={"status": "completed", "output": output},
        )

    async def wait_for_process(
        self, session_id: str, seconds: Optional[int] = None
    ) -> ToolResult:
        handle = self._session(session_id)
        if handle is None:
            return ToolResult(
                success=False,
                message=f"No active shell session: {session_id}",
                data={"status": "not_found", "returncode": None, "output": None},
            )
        wait_secs = min(max(seconds or 60, 1), 600)
        try:
            result = await asyncio.wait_for(handle.wait(), timeout=wait_secs)
            output = self._ansi_clean(
                (result.stdout or "") + (("\n" + result.stderr) if result.stderr else "")
            )
            return ToolResult(
                success=True,
                message="Process completed",
                data={
                    "status": "completed",
                    "returncode": result.exit_code,
                    "output": output,
                },
            )
        except asyncio.TimeoutError:
            output = self._ansi_clean(handle.stdout or "")
            return ToolResult(
                success=True,
                message="Process still running",
                data={"status": "running", "returncode": None, "output": output},
            )
        except Exception as exc:
            exit_code = getattr(exc, "exit_code", 1)
            stdout = getattr(exc, "stdout", "") or ""
            stderr = getattr(exc, "stderr", "") or ""
            return ToolResult(
                success=True,
                message="Process completed",
                data={
                    "status": "completed",
                    "returncode": exit_code,
                    "output": self._ansi_clean(stdout + (("\n" + stderr) if stderr else "")),
                },
            )

    async def write_to_process(
        self, session_id: str, input_text: str, press_enter: bool = True
    ) -> ToolResult:
        handle = self._session(session_id)
        if handle is None:
            return ToolResult(
                success=False,
                message=f"No active shell session: {session_id}",
                data={"status": "not_found"},
            )
        data = input_text + ("\n" if press_enter else "")
        try:
            await handle.send_stdin(data)
        except Exception as exc:
            return ToolResult(
                success=False,
                message=f"Failed to write to process: {exc}",
                data={"status": "failed"},
            )
        return ToolResult(
            success=True, message="Input written", data={"status": "completed"}
        )

    async def kill_process(self, session_id: str) -> ToolResult:
        handle = self._session(session_id)
        if handle is None:
            return ToolResult(
                success=False,
                message=f"No active shell session: {session_id}",
                data={"status": "not_found"},
            )
        try:
            await handle.kill()
        except Exception:
            pass
        self._shell_sessions.pop(session_id, None)
        return ToolResult(
            success=True, message="Process terminated", data={"status": "completed"}
        )

    # ------------------------------------------------------------------
    # File operations (E2B envd filesystem API + shell fallbacks)
    # ------------------------------------------------------------------

    @staticmethod
    def _norm(path: str) -> str:
        path = (path or "").strip()
        if not path.startswith("/"):
            path = f"/home/user/{path}"
        # collapse .. and .
        parts = []
        for part in path.split("/"):
            if part in ("", "."):
                continue
            if part == "..":
                if parts:
                    parts.pop()
                continue
            parts.append(part)
        return "/" + "/".join(parts)

    async def file_write(
        self,
        file: str,
        content: str,
        append: bool = False,
        leading_newline: bool = False,
        trailing_newline: bool = False,
        sudo: Optional[bool] = False,
    ) -> ToolResult:
        path = self._norm(file)
        if leading_newline:
            content = "\n" + content
        if trailing_newline:
            content = content + "\n"
        try:
            if append and content:
                # append via shell to avoid reading big files into memory
                esc = content.replace("'", "'\\''")
                out = await self._cmd(
                    f"mkdir -p \"$(dirname '{path}')\" && printf '%s' '{esc}' >> '{path}' && echo WROTE",
                    timeout=30,
                )
                if "WROTE" not in out:
                    raise RuntimeError("append failed")
            else:
                parent = "/".join(path.split("/")[:-1]) or "/"
                try:
                    await self._sbx.files.make_dir(parent)
                except Exception:
                    pass
                await self._sbx.files.write(path, content)
            return ToolResult(
                success=True,
                message=f"File written: {path}",
                data={"content": len(content)},
            )
        except Exception as exc:
            return ToolResult(
                success=False, message=f"Failed to write {path}: {exc}"
            )

    async def file_read(
        self,
        file: str,
        start_line: Optional[int] = None,
        end_line: Optional[int] = None,
        sudo: bool = False,
    ) -> ToolResult:
        path = self._norm(file)
        try:
            content = await self._sbx.files.read(path, format="text")
        except Exception as exc:
            return ToolResult(
                success=False, message=f"Failed to read {path}: {exc}"
            )
        if content is None:
            content = ""
        lines = content.splitlines()
        if start_line is not None or end_line is not None:
            start = start_line or 0
            end = end_line if end_line is not None else len(lines)
            content = "\n".join(lines[start:end])
        if len(content) > 10000:
            content = content[:10000] + "(truncated)"
        return ToolResult(
            success=True,
            message="File read successfully",
            data={"content": content},
        )

    async def file_exists(self, path: str) -> ToolResult:
        p = self._norm(path)
        try:
            exists = await self._sbx.files.exists(p)
        except Exception:
            exists = "YES" in await self._cmd(f"test -e '{p}' && echo YES || echo NO")
        return ToolResult(
            success=True,
            message="File exists check completed",
            data={"exists": bool(exists)},
        )

    async def file_delete(self, path: str) -> ToolResult:
        p = self._norm(path)
        try:
            await self._sbx.files.remove(p)
            return ToolResult(success=True, message=f"Deleted: {p}")
        except Exception as exc:
            return ToolResult(success=False, message=f"Failed to delete {p}: {exc}")

    async def file_move(self, source: str, destination: str) -> ToolResult:
        src, dst = self._norm(source), self._norm(destination)
        try:
            await self._sbx.files.rename(src, dst)
            return ToolResult(
                success=True, message=f"Moved: {src} → {dst}"
            )
        except Exception:
            out = await self._cmd(
                f"mkdir -p \"$(dirname '{dst}')\" && mv '{src}' '{dst}' && echo OK",
                timeout=30,
            )
            if "OK" in out:
                return ToolResult(success=True, message=f"Moved: {src} → {dst}")
            return ToolResult(
                success=False, message=f"Failed to move {src} → {dst}"
            )

    async def file_copy(self, source: str, destination: str) -> ToolResult:
        src, dst = self._norm(source), self._norm(destination)
        out = await self._cmd(
            f"mkdir -p \"$(dirname '{dst}')\" && cp -r '{src}' '{dst}' && echo OK",
            timeout=60,
        )
        if "OK" in out:
            return ToolResult(success=True, message=f"Copied: {src} → {dst}")
        return ToolResult(success=False, message=f"Failed to copy {src} → {dst}")

    async def file_list(self, path: str) -> ToolResult:
        p = self._norm(path)
        try:
            entries = await self._sbx.files.list(p)
        except Exception as exc:
            return ToolResult(
                success=False, message=f"Failed to list directory {p}: {exc}"
            )
        norm_entries = []
        for e in entries or []:
            name = getattr(e, "name", None) or ""
            etype = getattr(e, "type", None)
            type_str = "dir" if str(etype).upper().endswith("DIRECTORY") or str(etype).upper() == "DIR" else "file"
            size = getattr(e, "size", None) or 0
            norm_entries.append(
                {"name": name, "type": type_str, "size": int(size or 0)}
            )
        listing = "\n".join(
            f"{e['type']:4s} {str(e['size']):>10s}  {e['name']}" for e in norm_entries
        )
        return ToolResult(
            success=True,
            message=f"Directory listed: {len(norm_entries)} entry(ies)",
            data={"listing": listing, "entries": norm_entries},
        )

    async def file_replace(
        self, file: str, old_str: str, new_str: str, sudo: bool = False
    ) -> ToolResult:
        read = await self.file_read(file)
        if not read.success or not isinstance(read.data, dict):
            return ToolResult(
                success=False,
                message=f"Failed to read {file} for replacement",
            )
        content = read.data.get("content", "")
        if old_str not in content:
            return ToolResult(
                success=False,
                message=f"String not found in {file}",
            )
        new_content = content.replace(old_str, new_str)
        write = await self.file_write(file, new_content)
        if not write.success:
            return write
        return ToolResult(
            success=True,
            message=f"Replaced {content.count(old_str)} occurrence(s) in {file}",
        )

    async def file_search(
        self, file: str, regex: str, sudo: bool = False
    ) -> ToolResult:
        path = self._norm(file)
        esc_regex = regex.replace("'", "'\\''")
        out = await self._cmd(
            f"grep -nE '{esc_regex}' '{path}' | head -50; true", timeout=30
        )
        return ToolResult(
            success=True,
            message="Search completed",
            data={"matches": out or "(no matches)"},
        )

    async def file_find(self, path: str, glob_pattern: str) -> ToolResult:
        p = self._norm(path)
        esc_glob = glob_pattern.replace("'", "'\\''")
        out = await self._cmd(
            f"find '{p}' -maxdepth 4 -name '{esc_glob}' 2>/dev/null | head -100; true",
            timeout=30,
        )
        files = [line for line in (out or "").splitlines() if line.strip()]
        return ToolResult(
            success=True,
            message=f"Found {len(files)} file(s)",
            data={"files": files},
        )

    async def file_upload(
        self,
        file_data: BinaryIO,
        path: str,
        filename: Optional[str] = None,
    ) -> ToolResult:
        p = self._norm(path)
        if not p.endswith("/") and filename:
            # path is a directory → join filename
            if "YES" in await self._cmd(f"test -d '{p}' && echo YES || echo NO"):
                p = f"{p}/{filename}"
        data = file_data.read()
        try:
            parent = "/".join(p.split("/")[:-1]) or "/"
            try:
                await self._sbx.files.make_dir(parent)
            except Exception:
                pass
            await self._sbx.files.write(p, data)
            return ToolResult(
                success=True, message=f"Uploaded: {p}", data={"path": p}
            )
        except Exception as exc:
            return ToolResult(success=False, message=f"Upload failed: {exc}")

    async def file_download(self, path: str) -> BinaryIO:
        p = self._norm(path)
        data = await self._sbx.files.read(p, format="bytes")
        return io.BytesIO(data)

    # ------------------------------------------------------------------
    # UserScopedSandbox compatibility (own VM → own home)
    # ------------------------------------------------------------------

    async def setup_user_home(self) -> None:
        await self._cmd("mkdir -p /home/user/upload")

    @property
    def user_home(self) -> str:
        return "/home/user"

    @property
    def upload_dir(self) -> str:
        return "/home/user/upload"

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def id(self) -> str:
        return self._id

    @property
    def cdp_url(self) -> str:
        try:
            host = self._sbx.get_host(_CDP_PROXY_PORT)
            return f"wss://{host}"
        except Exception:
            return ""

    @property
    def vnc_url(self) -> str:
        # E2B phase 1 runs headless Chromium — live VNC view is not available;
        # the agent's browser_view screenshots still work via CDP.
        return ""
