from typing import Optional, AsyncGenerator, List
import asyncio
import base64
import logging
import os
try:
    import debugpy
except ImportError:
    debugpy = None
from pydantic import TypeAdapter
from app.domain.models.message import Message, VisionImage, is_vision_capable
from app.domain.services import file_extractor
from app.domain.models.event import (
    BaseEvent,
    ErrorEvent,
    TitleEvent,
    MessageEvent,
    MessageChunkEvent,
    DoneEvent,
    ToolEvent,
    WaitEvent,
    FileToolContent,
    ShellToolContent,
    SearchToolContent,
    BrowserToolContent,
    ImageToolContent,
    ToolStatus,
    AgentEvent,
    McpToolContent,
    PlanEvent,
    PlanStatus,
    StepEvent,
    StepStatus,
)
from app.domain.services.flows.plan_act import PlanActFlow
from app.domain.services.flows.plan_act_graph import PlanActGraphFlow
from app.domain.services.agents.zip_delivery import drop_zip_member_attachments
from app.core.config import get_settings
from app.domain.external.sandbox import Sandbox
from app.domain.external.browser import Browser
from app.domain.external.search import SearchEngine
from app.domain.external.file import FileStorage
from app.domain.repositories.agent_repository import AgentRepository
from app.domain.external.task import TaskRunner, Task
from app.domain.repositories.session_repository import SessionRepository
from app.domain.repositories.mcp_repository import MCPRepository
from app.domain.models.session import SessionStatus
from app.domain.models.file import FileInfo
from app.domain.services.tools.mcp import MCPToolkit
from app.domain.models.tool_result import ToolResult
from app.domain.models.search import SearchResults

logger = logging.getLogger(__name__)


def _friendly_task_error(exc: Exception) -> str:
    """Translate raw provider exceptions into a clear, actionable message.

    Raw exceptions like ``Error code: 401 - {'error': {'message': ...}}`` are
    meaningless to end users. Map the common provider failures to short,
    actionable guidance while the full traceback still goes to the server log.
    """
    import openai as _openai

    if isinstance(exc, _openai.AuthenticationError):
        return (
            "API key ditolak oleh provider (401). Periksa kecocokan API_KEY dan "
            "API_BASE — key NVIDIA (nvapi-…) hanya untuk "
            "https://integrate.api.nvidia.com/v1, key OpenRouter (sk-or-…) hanya "
            "untuk https://openrouter.ai/api/v1. / The API key was rejected: make "
            "sure API_KEY matches API_BASE, then restart the app."
        )
    if isinstance(exc, _openai.RateLimitError):
        return (
            "Model provider sedang membatasi permintaan (429 / kuota habis). "
            "Tunggu beberapa saat lalu coba lagi, atau ganti API key/provider. / "
            "Rate limit reached — wait a moment or switch to another API key."
        )
    if isinstance(exc, _openai.PermissionDeniedError):
        return (
            "API key tidak memiliki akses ke model ini (403). Periksa MODEL_NAME "
            "dan paket kuota akun Anda. / The API key cannot access this model — "
            "check MODEL_NAME and your account quota."
        )
    if isinstance(exc, _openai.NotFoundError) and "model" in str(exc).lower():
        return (
            "Model tidak ditemukan (404). MODEL_NAME mungkin sudah tidak tersedia "
            "di provider — ganti ke model yang aktif. / Model not found — update "
            "MODEL_NAME to an available model and restart."
        )
    return f"Task error: {exc}"

class AgentTaskRunner(TaskRunner):
    """Agent task that can be cancelled"""
    def __init__(
        self,
        session_id: str,
        agent_id: str,
        user_id: str,
        sandbox: Sandbox,
        browser: Browser,
        agent_repository: AgentRepository,
        session_repository: SessionRepository,
        file_storage: FileStorage,
        mcp_repository: MCPRepository,
        search_engine: Optional[SearchEngine] = None,
        project_instruction: Optional[str] = None,
    ):
        self._session_id = session_id
        self._agent_id = agent_id
        self._user_id = user_id
        self._sandbox = sandbox
        self._browser = browser
        self._search_engine = search_engine
        self._repository = agent_repository
        self._session_repository = session_repository
        self._file_storage = file_storage
        self._mcp_repository = mcp_repository
        self._mcp_tool = MCPToolkit()
        # Pre-edit snapshots per tool_call_id so the UI can show the Diff /
        # Original / Modified tabs (official Manus text_editor behaviour):
        # captured when a file_write / file_str_replace CALLING event arrives,
        # consumed when the matching CALLED event is enriched with content.
        self._file_old_by_call: Dict[str, str] = {}
        # Circuit breaker for panel-preview screenshots: when the browser VM is
        # under load each failed capture costs a full 10 s deadline. After a
        # timeout, skip further attempts for a while so tool events keep
        # flowing at full speed (the VNC takeover view still shows the page).
        self._screenshot_skip_until: float = 0.0
        # Newest screenshot file id for this task (retention: delete the
        # previous preview when a new one uploads — see _get_browser_screenshot).
        self._last_screenshot_id: Optional[str] = None

        # Orchestration engine switch (data-driven, no code edit needed):
        #   AGENT_FLOW_ENGINE=langgraph → LangGraph StateGraph driver (default)
        #   AGENT_FLOW_ENGINE=custom    → original hand-rolled while-loop
        # Both classes share the SAME agents, prompts, tools and event
        # contract — see flows/plan_act_graph.py.
        _flow_cls = (
            PlanActGraphFlow
            if get_settings().agent_flow_engine == "langgraph"
            else PlanActFlow
        )
        self._flow = _flow_cls(
            self._agent_id,
            self._repository,
            self._session_id,
            self._session_repository,
            self._sandbox,
            self._browser,
            self._mcp_tool,
            self._search_engine,
            project_instruction=project_instruction,
        )
        # The Task currently being pumped by run(). The rate-limit notice
        # callback (fired from inside the agents' retry loops) needs it to
        # stream "waiting for the provider" messages into the chat.
        self._active_task = None
        # Wire the agents' patient-retry notices into the chat stream so a
        # multi-minute provider rate limit shows as a friendly waiting
        # message instead of a frozen screen.
        for _agent in (self._flow.planner, self._flow.executor):
            _agent.rate_limit_notice = self._emit_rate_limit_notice

    async def _emit_rate_limit_notice(self, text: str) -> None:
        """User-facing notice while the agent waits out a provider rate limit.

        Called (and awaited) from BaseAgent's patient 429 retry loop. Emits a
        progress message into the live chat stream and persists it, so both
        live viewers and replay users see that the task is waiting, not dead.
        Best-effort: a failure here must never break the retry loop itself.
        """
        task = self._active_task
        if task is None:
            return
        try:
            await self._put_and_add_event(
                task, MessageEvent(role="assistant", message=text, is_progress=True)
            )
        except Exception:
            logger.debug("rate-limit notice could not be emitted", exc_info=True)

    async def _put_and_add_event(self, task: Task, event: AgentEvent) -> None:
        event_id = await task.output_stream.put(event.model_dump_json())
        event.id = event_id
        # MessageChunkEvents are transient streaming tokens — stream them to the
        # client in real time but do NOT persist them to the session history.
        if not isinstance(event, MessageChunkEvent):
            await self._session_repository.add_event(self._session_id, event)
    
    async def _pop_event(self, task: Task) -> Optional[AgentEvent]:
        event_id, event_str = await task.input_stream.pop()
        if event_str is None:
            logger.warning(f"Agent {self._agent_id} received empty message from input stream")
            return None
        event = TypeAdapter(AgentEvent).validate_json(event_str)
        event.id = event_id
        return event
    
    async def _get_browser_screenshot(self) -> str:
        """Capture the current page for the tool panel — strictly best-effort.

        The browser may be busy rendering a heavy page (or the CDP websocket
        may go silent) right after a click/navigation. The agent task must
        NEVER stall on a panel preview: short deadline, swallow every failure
        and return "" so the tool event still flows through immediately.
        """
        try:
            import time as _time
            if _time.monotonic() < self._screenshot_skip_until:
                # A recent capture timed out — the browser is busy/thrashing;
                # skip preview attempts until the breaker window expires.
                return ""
            screenshot = await asyncio.wait_for(
                self._browser.screenshot(), timeout=10.0
            )
        except asyncio.TimeoutError:
            import time as _time
            self._screenshot_skip_until = _time.monotonic() + 120.0
            logger.warning(
                "Browser screenshot timed out (10s) — skipping panel preview "
                "for 120s (circuit breaker)"
            )
            return ""
        except Exception as e:
            logger.warning(f"Browser screenshot failed — skipping panel preview: {e}")
            return ""
        try:
            result = await self._file_storage.upload_file(screenshot, "screenshot.png", self._user_id)
            # Retention: browser screenshots are transient panel previews.
            # Keeping every one (~1.5MB each, dozens per task) exhausted the
            # 512MB Atlas free tier mid-task and blocked ALL writes (task
            # died). Keep only the newest per session: delete the previous
            # one now that the new upload succeeded.
            prev = self._last_screenshot_id
            self._last_screenshot_id = result.file_id
            if prev and prev != result.file_id:
                try:
                    await self._file_storage.delete_file(prev, self._user_id)
                except Exception as del_exc:
                    # Best-effort only — a stale preview lingering in GridFS
                    # is harmless compared to breaking the tool event flow.
                    logger.debug(f"Old screenshot {prev} cleanup skipped: {del_exc}")
            return result.file_id
        except Exception as e:
            logger.warning(f"Browser screenshot upload failed: {e}")
            return ""

    async def _sync_file_to_storage(self, file_path: str) -> Optional[FileInfo]:
        """Upload or update file and return FileInfo"""
        import mimetypes
        try:
            file_info = await self._session_repository.get_file_by_path(self._session_id, file_path)
            file_data = await self._sandbox.file_download(file_path)
            if file_info:
                await self._session_repository.remove_file(self._session_id, file_info.file_id)
            file_name = file_path.split("/")[-1]
            content_type, _ = mimetypes.guess_type(file_name)
            file_info = await self._file_storage.upload_file(file_data, file_name, self._user_id, content_type=content_type)
            file_info.file_path = file_path
            await self._session_repository.add_file(self._session_id, file_info)
            return file_info
        except Exception as e:
            # Concise one-line warning — a full traceback here floods the
            # console and looks broken to users watching the logs. Missing
            # files are common when the model *claims* an output before the
            # command that creates it has run; the path is retried later at
            # step completion / final summary (see _sync_run_artifacts).
            logger.warning(
                "Agent %s could not sync %s yet (%s) — will retry at the "
                "next sync point",
                self._agent_id, file_path, type(e).__name__,
            )

    # ── User-home artifact scan ────────────────────────────────────────────────
    # Shell-created files (`cat > index.html <<EOF`, scripts, exports…) are
    # invisible to the file_write tracking above, and models sometimes CLAIM
    # an output file before actually creating it. Scanning the user's home
    # directory and diffing against a baseline taken at task start makes
    # delivery deterministic: whatever actually exists at the end gets
    # delivered with the summary — no matter how it was created.
    _SCAN_MAX_DEPTH = 3
    _SCAN_MAX_ENTRIES = 400
    # Dependency / runtime caches that must NEVER be treated as user
    # artifacts. A single `npm install` creates hundreds of node_modules
    # files; syncing them one-by-one froze a live task for 2m46s (every
    # step/plan event was held hostage behind the uploads) and burned ~400
    # GridFS uploads on the 512MB Atlas tier. They are restorable with a
    # package manager — never deliverables. (Dot-directories like .git are
    # already skipped by the dotfile rule below.)
    _SCAN_JUNK_DIRS = frozenset({
        "node_modules", "bower_components", "__pycache__", "venv",
        "target", "coverage",
    })

    async def _scan_user_home_files(self) -> dict:
        """Recursively map {absolute_path: size} for files under the user home.

        Skips the upload/ landing zone (files the user sent — already in
        storage) and dotfiles. Returns {} when the sandbox has no user_home
        concept or the directory is not listable — never raises.
        """
        home = getattr(self._sandbox, "user_home", None)
        if not home:
            return {}
        found: dict = {}

        async def _walk(path: str, depth: int) -> None:
            if depth > self._SCAN_MAX_DEPTH or len(found) >= self._SCAN_MAX_ENTRIES:
                return
            try:
                result = await self._sandbox.file_list(path)
            except Exception:
                return
            if not (result and result.success and result.data):
                return
            # result.data arrives as a DICT from the sandbox HTTP API
            # (ToolResult.data) — getattr() would look for an *attribute*
            # named "entries" and always miss the dict key, silently
            # disabling the whole artifact scan (shell-created files never
            # reached the user). Access both shapes defensively.
            data = result.data
            raw_entries = (
                data.get("entries")
                if isinstance(data, dict)
                else getattr(data, "entries", None)
            ) or []
            for entry in raw_entries:
                if isinstance(entry, dict):
                    name = entry.get("name") or ""
                    is_dir = entry.get("type") == "dir"
                    size = entry.get("size") or 0
                else:
                    name = getattr(entry, "name", "")
                    is_dir = getattr(entry, "type", "") == "dir"
                    size = getattr(entry, "size", 0) or 0
                if not name or name.startswith("."):
                    continue
                child = f"{path.rstrip('/')}/{name}"
                if is_dir:
                    if name == "upload" or name in self._SCAN_JUNK_DIRS:
                        continue
                    await _walk(child, depth + 1)
                else:
                    found[child] = size or 0

        await _walk(home, 0)
        return found

    async def _sync_run_artifacts(
        self,
        baseline: dict,
        files_written: List[FileInfo],
        pending: set,
    ) -> None:
        """Sync every new/changed file in the user home + retry pending paths.

        Called at each step completion and right before the final summary is
        assembled — the moments when the shell has usually finished writing.
        Files already tracked in files_written keep their latest synced
        version only when the on-disk size changed.
        """
        candidates: List[str] = []

        current = await self._scan_user_home_files()
        if current:
            tracked_sizes = {
                fw.file_path: None for fw in files_written
            }  # presence only; size of the synced copy is unknown
            for path, size in current.items():
                base_size = baseline.get(path)
                if base_size is None or base_size != size:
                    if path not in tracked_sizes or base_size is not None:
                        candidates.append(path)
        # Retry paths that failed earlier (claimed before they existed).
        candidates.extend(p for p in pending if p not in candidates)

        for path in candidates:
            try:
                file_info = await self._sync_file_to_storage(path)
            except Exception as e:
                logger.warning("Artifact sync failed for %s: %s", path, e)
                continue
            if file_info:
                pending.discard(path)
                baseline[path] = current.get(path, file_info.size or 0)
                files_written[:] = [
                    f for f in files_written if f.file_path != file_info.file_path
                ]
                files_written.append(file_info)
                logger.info(
                    "Agent %s artifact delivered: %s", self._agent_id, path
                )
            else:
                pending.add(path)
    
    async def _sync_file_to_sandbox(self, file_id: str) -> Optional[FileInfo]:
        """Download file from storage to sandbox.

        Always returns FileInfo when the GridFS download succeeds, even if the
        sandbox upload fails.  Vision images and text-extractable files only
        need the file_id (they pull bytes from GridFS directly), so dropping
        the attachment when the sandbox path fails would silently block vision
        processing.  file_path is set only when the sandbox upload succeeds;
        the downstream code already filters sandbox_attachments by file_path.
        """
        # Step 1: Download from GridFS — if this fails there is nothing to do.
        try:
            file_data, file_info = await self._file_storage.download_file(file_id, self._user_id)
        except Exception as e:
            logger.exception(f"Agent {self._agent_id} failed to download file {file_id} from storage: {e}")
            return None

        # Step 2: Upload to sandbox filesystem — non-fatal; vision/extractable
        # files don't need the sandbox path so we proceed regardless.
        safe_name = f"{file_id[:8]}_{file_info.filename}" if file_info.filename else file_id
        upload_dir = getattr(self._sandbox, 'upload_dir', '/home/runner/upload')
        file_path = f"{upload_dir}/{safe_name}"
        try:
            result = await self._sandbox.file_upload(file_data, file_path)
            if result.success:
                file_info.file_path = file_path
                logger.debug(f"Agent {self._agent_id}: file {file_info.filename!r} uploaded to sandbox at {file_path}")
            else:
                logger.warning(
                    f"Agent {self._agent_id}: sandbox upload returned failure for {file_info.filename!r} "
                    f"(file_id={file_id}) — keeping file_id for vision/extraction fallback"
                )
        except Exception as e:
            logger.warning(
                f"Agent {self._agent_id}: sandbox upload raised exception for {file_info.filename!r} "
                f"(file_id={file_id}): {e} — keeping file_id for vision/extraction fallback"
            )

        return file_info

    async def _sync_message_attachments_to_storage(self, event: MessageEvent) -> None:
        """Sync message attachments and update event attachments"""
        attachments: List[FileInfo] = []
        try:
            if event.attachments:
                for attachment in event.attachments:
                    # Skip re-syncing files that are already uploaded to storage
                    if attachment.file_id:
                        attachments.append(attachment)
                        continue
                    file_info = await self._sync_file_to_storage(attachment.file_path)
                    if file_info:
                        attachments.append(file_info)
            event.attachments = attachments
        except Exception as e:
            logger.exception(f"Agent {self._agent_id} failed to sync attachments to storage: {e}")
    
    async def _sync_message_attachments_to_sandbox(self, event: MessageEvent) -> None:
        """Sync message attachments and update event attachments"""
        attachments: List[FileInfo] = []
        try:
            if event.attachments:
                for attachment in event.attachments:
                    file_info = await self._sync_file_to_sandbox(attachment.file_id)
                    if file_info:
                        attachments.append(file_info)
                        await self._session_repository.add_file(self._session_id, file_info)
            event.attachments = attachments
        except Exception as e:
            logger.exception(f"Agent {self._agent_id} failed to sync attachments to event: {e}")
    

    # File-writing function names — these produce output files we should deliver to the user
    _FILE_WRITE_FUNCTIONS = {"file_write", "file_str_replace", "image_download"}

    # TODO: refactor this function
    async def _handle_tool_event(self, event: ToolEvent) -> Optional[FileInfo]:
        """Generate tool content. Returns FileInfo when a file is written to storage."""
        synced_file: Optional[FileInfo] = None
        try:
            # Capture pre-write file content so the UI can show Diff / Original.
            if (
                event.status == ToolStatus.CALLING
                and event.tool_name == "file"
                and event.function_name in ("file_write", "file_str_replace")
                and "file" in event.function_args
            ):
                try:
                    file_path = event.function_args["file"]
                    prior = await self._sandbox.file_read(file_path)
                    if prior and prior.success and isinstance(prior.data, dict):
                        self._file_old_by_call[event.tool_call_id] = prior.data.get("content", "") or ""
                except Exception:
                    # New file / missing file — no original content.
                    logger.debug(
                        f"Agent {self._agent_id} no prior content for {event.function_args.get('file')}"
                    )
            if event.status == ToolStatus.CALLED:
                if event.tool_name == "browser":
                    screenshot = await self._get_browser_screenshot()
                    if event.function_name == "browser_console_exec":
                        js_code = event.function_args.get("javascript", "")
                        js_result = None
                        if event.function_result and hasattr(event.function_result, "data"):
                            js_result = (event.function_result.data or {}).get("result")
                        event.tool_content = BrowserToolContent(screenshot=screenshot, js_code=js_code, js_result=js_result)
                    elif event.function_name == "browser_console_view":
                        js_result = None
                        if event.function_result and hasattr(event.function_result, "data"):
                            js_result = (event.function_result.data or {}).get("logs")
                        event.tool_content = BrowserToolContent(screenshot=screenshot, js_result=js_result)
                    else:
                        event.tool_content = BrowserToolContent(screenshot=screenshot)
                elif event.tool_name == "search":
                    search_results: ToolResult[SearchResults] = event.function_result
                    logger.debug(f"Search tool results: {search_results}")
                    event.tool_content = SearchToolContent(results=search_results.data.results)
                elif event.tool_name == "shell":
                    if "id" in event.function_args:
                        shell_result = await self._sandbox.view_shell(event.function_args["id"], console=True)
                        console_data = (shell_result.data or {}).get("console", []) if (shell_result and shell_result.success) else []
                        event.tool_content = ShellToolContent(console=console_data)
                    else:
                        event.tool_content = ShellToolContent(console="(No Console)")
                elif event.tool_name == "file":
                    fn = event.function_name
                    result = event.function_result
                    if fn in ("file_list_dir", "file_find_by_name"):
                        # Directory listing / file search: show the real
                        # listing text instead of a misleading "(No Content)".
                        # file_list_dir data = {"listing": str, "entries": [...]};
                        # file_find_by_name data = {"path": str, "files": [...]}.
                        listing = ""
                        if result and result.success and isinstance(result.data, dict):
                            listing = result.data.get("listing", "") or ""
                            if not listing and fn == "file_find_by_name":
                                listing = "\n".join(result.data.get("files") or [])
                        if not listing:
                            listing = (result.message if result else "") or "(No Content)"
                        event.tool_content = FileToolContent(content=listing)
                    elif fn in ("file_delete", "file_move", "file_copy"):
                        # Status operations: show the actual result message
                        # (e.g. "Deleted: /path", "Moved: a → b") — the file no
                        # longer exists at the source so there is no content to
                        # display, but the viewer must not look empty/blank.
                        msg = (result.message if result else "") or "(No Content)"
                        event.tool_content = FileToolContent(content=msg)
                    elif "file" in event.function_args:
                        file_path = event.function_args["file"]
                        file_read_result = await self._sandbox.file_read(file_path)
                        file_content: str = (file_read_result.data or {}).get("content", "") if (file_read_result and file_read_result.success) else ""
                        old_content = self._file_old_by_call.pop(event.tool_call_id, None)
                        # Only expose old_content when there was a prior snapshot
                        # (enables the Diff / Original / Modified tabs).
                        event.tool_content = FileToolContent(
                            content=file_content,
                            old_content=old_content,
                        )
                        if file_content:
                            file_info = await self._sync_file_to_storage(file_path)
                            # Track written files so they can be auto-attached to the response
                            if file_info and event.function_name in self._FILE_WRITE_FUNCTIONS:
                                synced_file = file_info
                    else:
                        event.tool_content = FileToolContent(content="(No Content)")
                elif event.tool_name == "image":
                    image_result = event.function_result
                    if event.function_name == "image_search_web":
                        results = []
                        if image_result and image_result.success and image_result.data:
                            results = image_result.data.results if hasattr(image_result.data, "results") else []
                        event.tool_content = ImageToolContent(results=results)
                    elif event.function_name == "image_generate":
                        gen_url = None
                        gen_prompt = event.function_args.get("prompt", "")
                        gen_model = event.function_args.get("model", "flux-schnell")
                        if image_result and image_result.success and image_result.data:
                            gen_url = getattr(image_result.data, "url", None)
                            gen_prompt = getattr(image_result.data, "revised_prompt", None) or gen_prompt
                            gen_model = getattr(image_result.data, "model", gen_model)
                        event.tool_content = ImageToolContent(
                            generated_url=gen_url,
                            generated_prompt=gen_prompt,
                            generated_model=gen_model,
                        )
                    elif event.function_name == "image_download":
                        file_path = event.function_args.get("file_path") or event.function_args.get("url", "")
                        downloaded = None
                        if image_result and image_result.success and image_result.data:
                            downloaded = image_result.data.get("file_path") if isinstance(image_result.data, dict) else None
                        downloaded_file_id = None
                        if downloaded:
                            synced_file = await self._sync_file_to_storage(downloaded)
                            if synced_file and synced_file.file_id:
                                downloaded_file_id = synced_file.file_id
                        event.tool_content = ImageToolContent(
                            downloaded_file=downloaded or file_path,
                            downloaded_file_id=downloaded_file_id,
                        )
                elif event.tool_name == "message":
                    # message_notify_user / message_ask_user — no special content needed,
                    # the text is streamed directly by the execution agent.
                    logger.debug(f"Agent {self._agent_id} received message tool event: {event.function_name}")
                elif event.tool_name == "mcp":
                    logger.debug(f"Processing MCP tool event: function_result={event.function_result}")
                    if event.function_result:
                        if hasattr(event.function_result, 'data') and event.function_result.data:
                            logger.debug(f"MCP tool result data: {event.function_result.data}")
                            event.tool_content = McpToolContent(result=event.function_result.data)
                        elif hasattr(event.function_result, 'success') and event.function_result.success:
                            logger.debug(f"MCP tool result (success, no data): {event.function_result}")
                            result_data = event.function_result.model_dump() if hasattr(event.function_result, 'model_dump') else str(event.function_result)
                            event.tool_content = McpToolContent(result=result_data)
                        else:
                            logger.debug(f"MCP tool result (fallback): {event.function_result}")
                            event.tool_content = McpToolContent(result=str(event.function_result))
                    else:
                        logger.warning("MCP tool: No function_result found")
                        event.tool_content = McpToolContent(result="No result available")
                    
                    logger.debug(f"MCP tool_content set to: {event.tool_content}")
                    if event.tool_content:
                        logger.debug(f"MCP tool_content.result: {event.tool_content.result}")
                        logger.debug(f"MCP tool_content dict: {event.tool_content.model_dump()}")
                else:
                    logger.warning(f"Agent {self._agent_id} received unknown tool event: {event.tool_name}")
        except Exception as e:
            logger.exception(f"Agent {self._agent_id} failed to generate tool content: {e}")
        return synced_file

    async def run(self, task: Task) -> None:
        """Process agent's message queue and run the agent's flow"""
        self._active_task = task
        # True when the run ended with a WaitEvent (agent asked the user a
        # question) — in that case the sandbox must stay warm for the answer,
        # so the post-run quota-saving pause is skipped.
        waited_for_user = False
        try:
            logger.info(f"Agent {self._agent_id} message processing task started")

            # Kick off sandbox + MCP init concurrently in the background.
            # The planner only needs the LLM, so we can stream the initial
            # acknowledgment response to the user in < 1 s while the sandbox
            # warms up, exactly like Dzeck does.
            mcp_config = await self._mcp_repository.get_mcp_config()
            sandbox_task = asyncio.create_task(self._sandbox.ensure_sandbox())
            mcp_task = asyncio.create_task(self._mcp_tool.initialized(mcp_config))

            while not await task.input_stream.is_empty():
                event = await self._pop_event(task)
                message = ""
                if isinstance(event, MessageEvent):
                    message = event.message or ""
                    # File attachments require an active sandbox; wait only when needed
                    if event.attachments:
                        await sandbox_task
                        await self._sync_message_attachments_to_sandbox(event)

                logger.info(f"Agent {self._agent_id} received new message: {message[:50]}...")

                attachments_list = event.attachments if isinstance(event, MessageEvent) and event.attachments else []

                vision_images = []
                extracted_file_blocks: list[str] = []
                # All file_ids that have been fully handled server-side
                # (vision-encoded OR text-extracted) — these must NOT appear as
                # sandbox attachment paths so the AI never sees a file twice.
                handled_file_ids: set[str] = set()

                for attachment in attachments_list:
                    if not attachment.file_id:
                        continue
                    ct = attachment.content_type or ""
                    fname = attachment.filename or ""

                    if is_vision_capable(ct):
                        # Image → encode as vision data for the multimodal model
                        try:
                            file_data, _ = await self._file_storage.download_file(attachment.file_id, self._user_id)
                            raw = file_data.read()
                            b64 = base64.b64encode(raw).decode()
                            vision_images.append(VisionImage(
                                content_type=ct,
                                data=b64,
                            ))
                            # Mark handled — exclude sandbox path so the AI
                            # doesn't see the prefixed file name as a separate file
                            handled_file_ids.add(attachment.file_id)
                            logger.debug(f"Collected vision image for {fname} ({len(raw)} bytes)")
                        except Exception as ve:
                            logger.warning(f"Could not collect vision data for {fname}: {ve}")

                    elif file_extractor.is_extractable(fname, ct):
                        # Document / spreadsheet / text → extract server-side and inject as text
                        try:
                            file_data, _ = await self._file_storage.download_file(attachment.file_id, self._user_id)
                            raw = file_data.read()
                            extracted = file_extractor.extract_text(raw, fname, ct)
                            if extracted.strip():
                                extracted_file_blocks.append(
                                    f"<file name=\"{fname}\">\n{extracted}\n</file>"
                                )
                                # Mark handled — exclude sandbox path
                                handled_file_ids.add(attachment.file_id)
                                logger.info(
                                    f"Server-extracted {fname} ({len(raw)} bytes → {len(extracted)} chars)"
                                )
                        except Exception as fe:
                            # Extraction failed — keep it in attachments as fallback
                            logger.warning(f"Server extraction failed for {fname}, keeping as attachment: {fe}")

                # Prepend extracted file content to the message so the AI sees it immediately.
                # Format: user request first, then the file blocks as supporting context —
                # this prevents the AI from treating the file as "the request" and getting confused.
                if extracted_file_blocks:
                    files_block = "\n\n".join(extracted_file_blocks)
                    message = (
                        f"{message}\n\n"
                        f"[The following file(s) have been pre-extracted and are ready to analyze. "
                        f"Use this content directly — do NOT run any extraction commands.]\n\n"
                        f"{files_block}"
                    )
                    logger.info(
                        f"Injected {len(extracted_file_blocks)} extracted file(s) into message"
                    )

                # Only pass sandbox paths for files that were NOT handled server-side.
                # Handled files (vision-encoded or text-extracted) must be excluded so the
                # AI never sees a prefixed sandbox name alongside the original filename.
                sandbox_attachments = [
                    a.file_path
                    for a in attachments_list
                    if a.file_path and a.file_id not in handled_file_ids
                ]

                message_obj = Message(
                    message=message,
                    attachments=sandbox_attachments,
                    vision_images=vision_images,
                )
                
                async for event in self._run_flow(message_obj, sandbox_task, mcp_task):
                    await self._put_and_add_event(task, event)
                    if isinstance(event, TitleEvent):
                        await self._session_repository.update_title(self._session_id, event.title)
                    elif isinstance(event, MessageEvent):
                        await self._session_repository.update_latest_message(self._session_id, event.message, event.timestamp)
                        await self._session_repository.increment_unread_message_count(self._session_id)
                    elif isinstance(event, WaitEvent):
                        await self._session_repository.update_status(self._session_id, SessionStatus.WAITING)
                        waited_for_user = True
                        return
                    if not await task.input_stream.is_empty():
                        break

            await self._session_repository.update_status(self._session_id, SessionStatus.COMPLETED)
        except asyncio.CancelledError:
            logger.info(f"Agent {self._agent_id} task cancelled")
            await self._put_and_add_event(task, DoneEvent())
            await self._session_repository.update_status(self._session_id, SessionStatus.COMPLETED)
        except Exception as e:
            logger.exception(f"Agent {self._agent_id} task encountered exception: {str(e)}")
            
            # If debugger is attached, trigger breakpoint for debugging
            # You can also manually set ENABLE_DEBUG_BREAK=1 environment variable
            if debugpy and (debugpy.is_client_connected() or os.getenv('ENABLE_DEBUG_BREAK')):
                logger.debug("Debugger detected, triggering breakpoint")
                import traceback
                traceback.print_exc()
                debugpy.breakpoint()
            
            await self._put_and_add_event(task, ErrorEvent(error=_friendly_task_error(e)))
            await self._session_repository.update_status(self._session_id, SessionStatus.COMPLETED)
        finally:
            # ── E2B quota saver ────────────────────────────────────────────
            # The run has fully finished: the final summary was delivered and
            # there are no more queued user messages. Pause the E2B microVM so
            # it stops burning compute quota while idle — files and processes
            # survive (freeze/thaw) and the next message auto-resumes it in
            # seconds. Skipped while the agent waits for a user answer, and
            # silently skipped for sandboxes without pause() (shared Replit).
            if not waited_for_user:
                await self._pause_sandbox_after_run()
            # Never leave a stale Task reference behind — a notice fired after
            # run() finished must not write into a dead output stream.
            self._active_task = None

    async def _pause_sandbox_after_run(self) -> None:
        """Pause the session sandbox after a finished run to save E2B quota.

        Duck-typed: only sandboxes exposing an async ``pause()`` (E2B) are
        paused. The shared Replit sandbox has no pause() and keeps running —
        pausing it would break every other user on the same container.
        Failures are logged, never raised: a quota-saving optimisation must
        not be able to fail a task that already succeeded.

        Skipped while a live-view (takeover) viewer is connected: pausing
        freezes every process in the VM, which would kill the user's screen
        mid-view. The viewer-disconnect hook re-pauses a few minutes after
        the last viewer leaves (E2BSandbox._repause_when_idle).
        """
        pause = getattr(self._sandbox, "pause", None)
        if not callable(pause):
            return
        has_viewers = getattr(self._sandbox, "has_vnc_viewers", None)
        if callable(has_viewers) and has_viewers():
            logger.info(
                f"Agent {self._agent_id} run finished — sandbox pause deferred: "
                "live-view viewer still connected (re-pauses after they leave)"
            )
            return
        try:
            paused = await pause()
            if paused:
                logger.info(
                    f"Agent {self._agent_id} run finished — sandbox paused to "
                    "save E2B quota (auto-resumes on the next message)"
                )
        except Exception as exc:
            logger.warning(
                f"Agent {self._agent_id} post-run sandbox pause failed: {exc}"
            )

    async def _run_flow(self, message: Message, sandbox_task=None, mcp_task=None) -> AsyncGenerator[BaseEvent, None]:
        """Process a single message through the agent's flow and yield events.

        sandbox_task / mcp_task are asyncio.Task objects that were started in
        the background so the planner can stream its acknowledgment immediately.
        We await them right after the plan is yielded — before the executor
        ever touches the sandbox — guaranteeing the sandbox is ready for tools.
        """
        if not message.message:
            logger.warning(f"Agent {self._agent_id} received empty message")
            yield ErrorEvent(error="No message")
            return

        sandbox_ready = False
        # Collect files written during this run so we can auto-attach them to
        # the FINAL summary MessageEvent when the agent forgets to include them.
        # Files are NEVER attached to mid-task messages anymore — the user
        # wants every deliverable to arrive ONCE, at the end, with the summary
        # (Manus-style).
        files_written: List[FileInfo] = []
        # File paths already attached to ANY message in this run. Guarantees
        # each file is delivered to the user EXACTLY ONCE.
        delivered_paths: set = set()
        # Baseline snapshot of the user's sandbox home at task start. Diffing
        # against it at sync points reveals files created by ANY means —
        # shell heredocs (`cat > file <<EOF`), scripts the agent ran, or tools
        # — so every real artifact reaches the summary without depending on
        # the model remembering to claim it.
        home_baseline: dict = await self._scan_user_home_files()
        # Paths that were claimed but did not exist yet — retried at every
        # sync point until they appear (or the task ends).
        pending_sync: set = set()
        # ── Background artifact sync ──────────────────────────────────────
        # Step-completion artifact syncing must NEVER block the event pump.
        # Live incident (session 5a60e5b5): after a step whose shell ran
        # `npm install`, the runner uploaded ~400 node_modules files one-by-one
        # (2m46s) BEFORE yielding StepEvent(completed) — the plan panel froze
        # at 0/5 while the agent was already browser-testing, and every later
        # event (plan updates, next step) piled up behind the uploads.
        # Syncs now run as a chained background task (at most one at a time);
        # the final summary awaits it before its own sweep so no deliverable
        # is lost. Mutations of files_written/pending_sync/home_baseline are
        # in-place only (never rebind) so this task's references stay valid.
        artifact_sync_task: Optional[asyncio.Task] = None

        def _is_generator_script(fi: FileInfo) -> bool:
            name = fi.filename or fi.file_path or ""
            return name.endswith(".py")

        async for event in self._flow.run(message):
            if isinstance(event, ToolEvent):
                # TODO: move to tool function
                file_info = await self._handle_tool_event(event)
                if file_info:
                    # Deduplicate by file_path — keep the latest version.
                    # In-place mutation (never rebind): the background
                    # artifact-sync task holds a reference to this exact list.
                    files_written[:] = [f for f in files_written if f.file_path != file_info.file_path]
                    files_written.append(file_info)
            elif isinstance(event, StepEvent) and event.status == StepStatus.COMPLETED:
                # ── NON-BLOCKING step artifact sync ──────────────────────
                # Schedule the sync in the background and yield this event
                # (and everything the flow emits next) immediately — see
                # artifact_sync_task above for the incident this fixes.
                _prev_sync = artifact_sync_task
                _step = event.step

                async def _bg_step_sync(
                    prev: Optional[asyncio.Task] = _prev_sync,
                    step=_step,
                ) -> None:
                    try:
                        if prev is not None and not prev.done():
                            # Serialize syncs: a slower earlier step's sync
                            # must finish first so home scans never overlap
                            # on the same paths.
                            try:
                                await prev
                            except Exception:
                                pass
                        if step and step.attachments:
                            # Sync files explicitly listed in step.attachments
                            # (e.g. .pptx created by shell_exec). These are the
                            # agent's intended output files but are never
                            # tracked by file_write.
                            for attachment_path in step.attachments:
                                if not attachment_path:
                                    continue
                                try:
                                    file_info = await self._sync_file_to_storage(attachment_path)
                                    if file_info:
                                        files_written[:] = [f for f in files_written if f.file_path != file_info.file_path]
                                        files_written.append(file_info)
                                        logger.info(
                                            f"Agent {self._agent_id} synced step attachment: {attachment_path}"
                                        )
                                    else:
                                        pending_sync.add(attachment_path)
                                except Exception as e:
                                    logger.warning(
                                        f"Agent {self._agent_id} failed to sync step attachment {attachment_path}: {e}"
                                    )
                        # Artifact scan: catch everything the shell actually
                        # created in this step (heredocs, generated scripts,
                        # exports) — the deterministic path to "hasil selalu
                        # sampai ke user". Junk dirs (node_modules, …) are
                        # filtered inside the scan itself.
                        await self._sync_run_artifacts(home_baseline, files_written, pending_sync)
                    except Exception as e:
                        logger.warning(
                            f"Agent {self._agent_id} background artifact sync failed: {e}"
                        )

                artifact_sync_task = asyncio.create_task(_bg_step_sync())
            elif isinstance(event, MessageEvent):
                if event.is_final:
                    # ── Final summary message — THE single delivery point ─────
                    # A background step sync may still be uploading — wait for
                    # it here (NOT earlier) so its files land in files_written
                    # before the merge below, while step events themselves
                    # were never delayed.
                    if artifact_sync_task is not None:
                        try:
                            await artifact_sync_task
                        except Exception:
                            pass
                        artifact_sync_task = None
                    # Last artifact sweep before assembling the summary: the
                    # shell may still have been writing a moment ago (files
                    # claimed early, created late) — retry everything now.
                    await self._sync_run_artifacts(home_baseline, files_written, pending_sync)
                    # Attach everything the task produced that has not been
                    # delivered yet: the model's own attachments + every file
                    # written by tools during the run (minus generator scripts
                    # when real outputs exist) + files deferred from mid-task
                    # messages. Deduplicated by path, never re-sent.
                    merged: List[FileInfo] = list(event.attachments or [])
                    known_paths = {f.file_path for f in merged if f.file_path}
                    non_scripts = [f for f in files_written if not _is_generator_script(f)]
                    files_to_merge = non_scripts if non_scripts else files_written
                    for f in files_to_merge:
                        if (
                            f.file_path
                            and f.file_path not in known_paths
                            and f.file_path not in delivered_paths
                        ):
                            known_paths.add(f.file_path)
                            merged.append(f)
                    # ── ZIP-only delivery ─────────────────────────────────────
                    # The artifact sweep above re-adds every file the tools
                    # wrote — including the individual html/css/js sources
                    # that are already bundled inside a delivered .zip. Drop
                    # them: when an archive is delivered, the user receives
                    # ONLY the archive.
                    try:
                        if self._sandbox and any(
                            (f.file_path or "").lower().endswith(".zip")
                            for f in merged
                        ):
                            merged = await drop_zip_member_attachments(
                                self._sandbox, merged
                            )
                    except Exception as exc:
                        logger.warning(
                            "ZIP-only delivery filter failed (delivering "
                            "unfiltered list): %s",
                            exc,
                        )
                    event.attachments = merged or None
                    if len(merged) != len(files_written) or files_written:
                        logger.info(
                            f"Agent {self._agent_id} final summary delivers "
                            f"{len(merged)} file(s): "
                            f"{[f.filename or f.file_path for f in merged]}"
                        )
                elif event.attachments:
                    # ── Mid-task message — strip attachments entirely. ───────
                    # Progress notifications must stay pure text; the files
                    # ride along with the final summary instead. Park them in
                    # files_written (if not already tracked) so nothing is lost.
                    dropped = [f.filename or f.file_path for f in event.attachments]
                    logger.info(
                        f"Agent {self._agent_id} deferred mid-task attachment(s) "
                        f"to the final summary: {dropped}"
                    )
                    for f in event.attachments:
                        if f.file_path and all(
                            fw.file_path != f.file_path for fw in files_written
                        ):
                            files_written.append(f)
                    event.attachments = None
                # Record everything this message carries so no later message
                # (e.g. the final summary) sends the same file again.
                for f in (event.attachments or []):
                    if f.file_path:
                        delivered_paths.add(f.file_path)
                await self._sync_message_attachments_to_storage(event)

            yield event

            # After the plan has been streamed to the client, ensure the
            # sandbox and MCP tools are fully ready before the executor starts.
            # This is the exact point Dzeck uses: plan is visible, execution
            # hasn't started yet.
            if not sandbox_ready and isinstance(event, PlanEvent) and event.status == PlanStatus.CREATED:
                sandbox_ready = True
                tasks_to_await = [t for t in (sandbox_task, mcp_task) if t and not t.done()]
                if tasks_to_await:
                    logger.info(f"Agent {self._agent_id} awaiting background sandbox/MCP init before execution")
                    await asyncio.gather(*tasks_to_await, return_exceptions=True)
                    logger.info(f"Agent {self._agent_id} sandbox/MCP ready — starting execution")

        # A step sync can still be in flight when the flow ends (e.g. the
        # last step completed right before the summary message). Never orphan
        # it: finish the uploads before this generator reports completion.
        if artifact_sync_task is not None:
            try:
                await artifact_sync_task
            except Exception:
                pass
        logger.info(f"Agent {self._agent_id} completed processing one message")

    
    async def on_done(self, task: Task) -> None:
        """Called when the task is done"""
        logger.info(f"Agent {self._agent_id} task done")


    async def destroy(self) -> None:
        """Destroy the task and release resources"""
        logger.info("Starting to destroy agent task")
        
        # Destroy sandbox environment
        if self._sandbox:
            logger.debug(f"Destroying Agent {self._agent_id}'s sandbox environment")
            await self._sandbox.destroy()
        
        if self._mcp_tool:
            logger.debug(f"Destroying Agent {self._agent_id}'s MCP tool")
            await self._mcp_tool.cleanup()
        
        logger.debug(f"Agent {self._agent_id} has been fully closed and resources cleared")
