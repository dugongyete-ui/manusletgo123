from typing import Optional, AsyncGenerator, List
import asyncio
import base64
import logging
import os
import debugpy
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
)
from app.domain.services.flows.plan_act import PlanActFlow
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
        self._flow = PlanActFlow(
            self._agent_id,
            self._repository,
            self._session_id,
            self._session_repository,
            self._sandbox,
            self._browser,
            self._mcp_tool,
            self._search_engine,
        )

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
        screenshot = await self._browser.screenshot()
        result = await self._file_storage.upload_file(screenshot, "screenshot.png", self._user_id)
        return result.file_id

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
            logger.exception(f"Agent {self._agent_id} failed to sync file: {e}")
    
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
        file_path = "/home/runner/upload/" + safe_name
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
                    if "file" in event.function_args:
                        file_path = event.function_args["file"]
                        file_read_result = await self._sandbox.file_read(file_path)
                        file_content: str = (file_read_result.data or {}).get("content", "") if (file_read_result and file_read_result.success) else ""
                        event.tool_content = FileToolContent(content=file_content)
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
                    elif event.function_name == "image_download":
                        file_path = event.function_args.get("file_path") or event.function_args.get("url", "")
                        downloaded = None
                        if image_result and image_result.success and image_result.data:
                            downloaded = image_result.data.get("file_path") if isinstance(image_result.data, dict) else None
                        event.tool_content = ImageToolContent(downloaded_file=downloaded or file_path)
                        if downloaded:
                            synced_file = await self._sync_file_to_storage(downloaded)
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
            if debugpy.is_client_connected() or os.getenv('ENABLE_DEBUG_BREAK'):
                logger.debug("Debugger detected, triggering breakpoint")
                import traceback
                traceback.print_exc()
                debugpy.breakpoint()  # This will pause execution if a debugger is attached
            
            await self._put_and_add_event(task, ErrorEvent(error=f"Task error: {str(e)}"))
            await self._session_repository.update_status(self._session_id, SessionStatus.COMPLETED)
    
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
        # the final MessageEvent when the agent forgets to include them.
        files_written: List[FileInfo] = []

        async for event in self._flow.run(message):
            if isinstance(event, ToolEvent):
                # TODO: move to tool function
                file_info = await self._handle_tool_event(event)
                if file_info:
                    # Deduplicate by file_path — keep the latest version
                    files_written = [f for f in files_written if f.file_path != file_info.file_path]
                    files_written.append(file_info)
            elif isinstance(event, MessageEvent):
                # Always merge files_written into the message attachments.
                # The agent may attach some files (e.g. a summary .md) while
                # forgetting to include downloaded images — we merge both.
                if files_written:
                    existing_paths = {f.file_path for f in (event.attachments or []) if f.file_path}
                    extra = [f for f in files_written if f.file_path not in existing_paths]
                    if extra:
                        event.attachments = list(event.attachments or []) + extra
                        logger.info(
                            f"Agent {self._agent_id} merged {len(extra)} written file(s) "
                            f"into MessageEvent: {[f.filename for f in extra]}"
                        )
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
