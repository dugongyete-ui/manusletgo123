from pydantic import BaseModel, Field, RootModel
from typing import Dict, Any, Literal, Optional, Union, List, get_args
from datetime import datetime
import time
import uuid
from enum import Enum
from app.domain.models.plan import Plan, Step
from app.domain.models.file import FileInfo
import json
from app.domain.models.search import SearchResultItem
from app.domain.models.image import ImageSearchResultItem
from app.domain.models.validation import ValidationResult


class PlanStatus(str, Enum):
    """Plan status enum"""
    CREATED = "created"
    UPDATED = "updated"
    COMPLETED = "completed"


class StepStatus(str, Enum):
    """Step status enum"""
    STARTED = "started"
    FAILED = "failed"
    COMPLETED = "completed"


class ToolStatus(str, Enum):
    """Tool status enum"""
    CALLING = "calling"
    CALLED = "called"


class BaseEvent(BaseModel):
    """Base class for agent events"""
    type: Literal[""] = ""
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: datetime = Field(default_factory=lambda: datetime.now())

class ErrorEvent(BaseEvent):
    """Error event"""
    type: Literal["error"] = "error"
    error: str

class PlanEvent(BaseEvent):
    """Plan related events"""
    type: Literal["plan"] = "plan"
    plan: Plan
    status: PlanStatus
    step: Optional[Step] = None

class BrowserToolContent(BaseModel):
    """Browser tool content"""
    screenshot: str = ""
    js_code: Optional[str] = None
    js_result: Optional[Any] = None

class SearchToolContent(BaseModel):
    """Search tool content"""
    results: List[SearchResultItem]

class ShellToolContent(BaseModel):
    """Shell tool content"""
    console: Any
    # Resolved shell session id. The agent may omit the `id` argument on
    # shell_exec (recommended: the toolkit auto-creates a fresh session), so
    # the frontend needs the ACTUAL id — echoed here from the tool result —
    # to poll live console output via /sessions/{id}/shell.
    session_id: Optional[str] = None

class FileToolContent(BaseModel):
    """File tool content"""
    content: str
    # Pre-edit snapshot so the UI can show Diff / Original / Modified tabs
    # (official Manus text_editor behaviour). Only present when the file
    # already existed before file_write / file_str_replace modified it.
    old_content: Optional[str] = None

class McpToolContent(BaseModel):
    """MCP tool content"""
    result: Any

class ImageToolContent(BaseModel):
    """Image tool content — search results, download confirmation, or generated image"""
    results: List[ImageSearchResultItem] = Field(default_factory=list)
    downloaded_file: Optional[str] = None
    downloaded_file_id: Optional[str] = None
    downloaded_signed_url: Optional[str] = None
    generated_url: Optional[str] = None
    generated_prompt: Optional[str] = None
    generated_model: Optional[str] = None

ToolContent = Union[
    BrowserToolContent,
    SearchToolContent,
    ShellToolContent,
    FileToolContent,
    McpToolContent,
    ImageToolContent,
]

class ToolEvent(BaseEvent):
    """Tool related events"""
    type: Literal["tool"] = "tool"
    tool_call_id: str
    tool_name: str
    tool_content: Optional[ToolContent] = None
    function_name: str
    function_args: Dict[str, Any]
    status: ToolStatus
    function_result: Optional[Any] = None
    # Official Manus StandardToolUsed prefers ``brief`` (natural-language
    # action label supplied by the model) over raw paths / commands.
    brief: Optional[str] = None

class TitleEvent(BaseEvent):
    """Title event"""
    type: Literal["title"] = "title"
    title: str

class StepEvent(BaseEvent):
    """Step related events"""
    type: Literal["step"] = "step"
    step: Step
    status: StepStatus

class MessageEvent(BaseEvent):
    """Message event"""
    type: Literal["message"] = "message"
    role: Literal["user", "assistant"] = "assistant"
    message: str
    attachments: Optional[List[FileInfo]] = None
    # True ONLY for the task's final summary message. Files created during
    # the task are never attached to mid-task messages — they are deferred
    # and delivered exactly once, here, with the final summary (Manus-style).
    is_final: bool = False
    # True for compact progress narrations (tool-progress lines, step
    # transitions). The frontend renders them INSIDE the unified step
    # timeline instead of standalone chat bubbles.
    is_progress: bool = False
    # True ONLY for agent questions that require a user answer (ask_user).
    # These must stay VISIBLE as standalone chat messages — they pause the
    # task — so the timeline must not swallow them.
    is_question: bool = False

class DoneEvent(BaseEvent):
    """Done event"""
    type: Literal["done"] = "done"

class WaitEvent(BaseEvent):
    """Wait event"""
    type: Literal["wait"] = "wait"

class MessageChunkEvent(BaseEvent):
    """Streaming message chunk — emitted token-by-token for the acknowledgment.
    The frontend accumulates these into a single message bubble.
    When done=True the stream for this message is complete."""
    type: Literal["message_chunk"] = "message_chunk"
    role: Literal["user", "assistant"] = "assistant"
    content: str = ""
    done: bool = False

class ValidationEvent(BaseEvent):
    """Final validation gate result — emitted once, right before the task's
    final summary message. Carries the mechanical checks, the execution
    summary counts, and the evidence register collected from the run."""
    type: Literal["validation"] = "validation"
    result: ValidationResult

AgentEvent = Union[
    ErrorEvent,
    PlanEvent, 
    ToolEvent,
    StepEvent,
    MessageEvent,
    MessageChunkEvent,
    ValidationEvent,
    DoneEvent,
    TitleEvent,
    WaitEvent,
]
