from typing import List, Callable
import inspect
import copy

from langchain_core.tools.structured import StructuredTool
from langchain.tools import BaseTool
from langchain.messages import ToolMessage
from langchain.messages import ToolCall
from langchain_core.tools.base import BaseToolkit as LangchainBaseToolkit, ArgsSchema
from typing import Any, Optional
from pydantic import BaseModel, create_model, ConfigDict, ValidationError

from app.domain.models.tool_result import ToolResult


def cap_tool_content(content: Any, limit: int) -> Any:
    """Cap a serialized tool result before it enters the LLM context.

    Tool results are serialized wholesale into ToolMessage.content and
    then re-sent to the provider on EVERY subsequent round. A single
    browser_view of a complex page or a file_read of a big file can
    carry 100-400K characters; left uncapped this is the fastest route
    to provider error 1261 "Prompt exceeds max length". The RAW result
    is preserved untouched on ToolMessage.artifact (the UI/timeline
    still sees everything) — only the LLM-facing copy is clipped.
    """
    if not isinstance(content, str) or limit <= 0 or len(content) <= limit:
        return content
    head = int(limit * 0.6)
    tail = max(0, limit - head)
    marker = (
        f"\n…[TRUNCATED {len(content) - limit} characters — the full result "
        "is preserved in the task artifact; re-run the tool, or use "
        "file_read / shell to view the full content again]…\n"
    )
    return content[:head] + marker + (content[-tail:] if tail else "")


def create_model_without_fields(model_class: type[BaseModel], exclude_fields: set[str]) -> type[BaseModel]:
    fields = {}
    for field_name, field_info in model_class.model_fields.items():
        if field_name not in exclude_fields:
            fields[field_name] = (field_info.annotation, field_info)
    return create_model(model_class.__name__, **fields)

class Tool(BaseTool):
    
    name: str = ""
    description: str = ""
    args_schema: ArgsSchema | None = None
    toolkit: 'BaseToolkit' = None

    def __init__(self, tool: StructuredTool, **kwargs: Any):
        super().__init__(**kwargs)
        self.name = tool.name
        self.description = tool.description
        self.args_schema = create_model_without_fields(tool.args_schema, {'self'})
        self._tool = tool

    def _run(self, **kwargs: Any) -> Any:
        return self._tool.func(self.toolkit, **kwargs)

    async def _arun(self, **kwargs: Any) -> Any:
        return await self._tool.coroutine(self.toolkit, **kwargs)

    def _signature_hint(self) -> str:
        """Human/LLM-readable list of accepted arguments with required flags.

        Derived from the tool's pydantic args_schema so the model can repair
        its next call without guessing (e.g. after omitting a required arg).
        """
        try:
            fields = self.args_schema.model_fields if self.args_schema else {}
            parts = []
            for name, field_info in fields.items():
                try:
                    required = bool(field_info.is_required())
                except Exception:
                    required = True
                parts.append(f"{name} ({'required' if required else 'optional'})")
            return ", ".join(parts)
        except Exception:
            return ""

    def _invalid_args_result(self, exc: Exception, args: dict) -> ToolResult:
        """Build an actionable failure for argument-mismatch errors.

        A raw ``TypeError: missing 1 required positional argument: 'file'``
        is a Python-internal message; the model retries the SAME broken call
        when that is all it sees (observed 4 identical failed file_write
        rounds in a live session). Listing what was sent vs. what the tool
        accepts lets the model repair the call in ONE round.
        """
        provided = ", ".join(sorted(args.keys())) if args else "(none)"
        hint = self._signature_hint()
        message = (
            f"Invalid arguments for {self.name}: {exc}. "
            f"Arguments you provided: [{provided}]."
        )
        if hint:
            message += f" Arguments accepted by {self.name}: {hint}."
        message += (
            " This call was NOT executed. Fix the arguments and call this"
            " tool again."
        )
        return ToolResult(success=False, message=message)

    async def ainvoke(self, input: Any, config: Any = None, **kwargs: Any) -> ToolMessage:
        """Invoke tool and return a ToolMessage with the raw result stored in artifact."""
        args = input.get("args", {}) if isinstance(input, dict) else {}
        tool_call_id = input.get("id", "") if isinstance(input, dict) else ""
        try:
            raw_result = await self._arun(**args)
        except (TypeError, ValidationError) as e:
            # Argument mismatch / schema validation failure — deterministic,
            # so retrying is pointless. Convert to a proper failed ToolResult
            # so BOTH the LLM (ToolMessage.content JSON) and the UI
            # (ToolEvent.function_result artifact) see the real error
            # instead of a null result rendered as "(No Content)".
            raw_result = self._invalid_args_result(e, args)
        content = raw_result.model_dump_json() if hasattr(raw_result, "model_dump_json") else str(raw_result)
        # Entry cap: keep one huge tool result from poisoning every later
        # LLM request (see cap_tool_content). The artifact stays complete.
        try:
            from app.core.config import get_settings as _get_settings
            _limit = int(getattr(_get_settings(), "tool_result_max_chars", 48_000) or 0)
        except Exception:
            _limit = 48_000
        content = cap_tool_content(content, _limit)
        return ToolMessage(tool_call_id=tool_call_id, name=self.name, content=content, artifact=raw_result)


class BaseToolkit(LangchainBaseToolkit):
    """Base toolset class, providing common tool calling methods"""

    name: str = ""
    tools: List[Tool] = []
    model_config = ConfigDict(ignored_types=(BaseTool,), extra='allow')

    def __init__(self):
        super().__init__()
        self.tools = []

        for _, tool in inspect.getmembers(self, lambda x: isinstance(x, BaseTool)):
            self.tools.append(Tool(tool, toolkit=self))
        
    

    def get_tools(self) -> List[Tool]:
        """Get all registered tools
        
        Returns:
            List of tools
        """
        return self.tools
    
    def get_tool(self, tool_name: str) -> Optional[Tool]:
        """Get specified tool
        
        Args:
            tool_name: Tool name
            
        Returns:
            Tool
        """
        for tool in self.tools:
            if tool.name == tool_name:
                return tool
        return None
