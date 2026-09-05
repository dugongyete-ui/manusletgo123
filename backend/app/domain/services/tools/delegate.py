"""Sub-agent delegation (Manus NestedExecutor equivalent).

``task_delegate`` lets the top-level executor hand one self-contained
subtask to a focused sub-agent that shares the SAME sandbox, browser and
files but works with its own clean context. The sub-agent runs a bounded
tool loop autonomously (it cannot ask the user anything) and returns a
final report as the tool result, which lands in the parent's context.

Depth is hard-capped at one level: the sub-agent's toolset deliberately
excludes task_delegate and message tools, so delegation can never recurse
and can never pause the parent task on a user question.
"""

from typing import Callable, List, Optional
import logging
import uuid

from app.domain.models.memory import Memory
from app.domain.services.tools.base import BaseToolkit
from app.domain.models.tool_result import ToolResult
from app.domain.external.sandbox import Sandbox
from app.domain.external.browser import Browser
from app.domain.external.search import SearchEngine
from app.domain.repositories.agent_repository import AgentRepository
from app.domain.services.tools.mcp import MCPToolkit
from langchain.messages import AIMessage as LCAIMessage
from langchain.tools import tool

logger = logging.getLogger(__name__)

# Bounded autonomy: enough rounds for a real subtask, never a runaway.
_NESTED_MAX_ITERATIONS = 25
# Keep the report digestible for the parent's context (chars).
_REPORT_MAX_CHARS = 8_000


class _TransientAgentRepository:
    """In-memory AgentRepository stand-in for NESTED agents.

    A sub-agent lives exactly as long as one task_delegate call: its memory
    is consumed in-process (the final report is read from the live object),
    so it must never touch MongoDB. Pointing it at the real repository made
    the very first save_memory fail with "Agent <nested-id> not found" —
    the nested id is deliberately never persisted — and persistence would
    also leak one garbage document per delegation. This wrapper keeps the
    AgentRepository protocol shape while storing everything locally.
    """

    def __init__(self) -> None:
        self._memories = {}

    async def save(self, agent) -> None:  # pragma: no cover — protocol shape
        return None

    async def find_by_id(self, agent_id: str):  # pragma: no cover
        return None

    async def add_memory(self, agent_id: str, name: str, memory: Memory) -> None:
        self._memories[name] = memory

    async def get_memory(self, agent_id: str, name: str) -> Memory:
        return self._memories.get(name, Memory(messages=[]))

    async def save_memory(self, agent_id: str, name: str, memory: Memory) -> None:
        self._memories[name] = memory


class DelegateToolkit(BaseToolkit):
    """Delegation tool — spawn a nested executor for one subtask."""

    name: str = "task"

    def __init__(
        self,
        sandbox: Sandbox,
        browser: Browser,
        mcp_tool: MCPToolkit,
        search_engine: Optional[SearchEngine],
        agent_id: str,
        agent_repository: AgentRepository,
        base_prompt: str,
        parent_context_provider: Optional[Callable[[], str]] = None,
    ):
        """``base_prompt`` is the flow's user-scoped system prompt (sandbox
        paths, security rules) — the sub-agent must obey the exact same
        environment contract as its parent.

        ``parent_context_provider`` returns a compact digest of the parent's
        recent memory so the sub-agent starts informed instead of blind.
        """
        super().__init__()
        self._sandbox = sandbox
        self._browser = browser
        self._mcp_tool = mcp_tool
        self._search_engine = search_engine
        self._agent_id = agent_id
        self._agent_repository = agent_repository
        self._base_prompt = base_prompt
        self._parent_context_provider = parent_context_provider

    def _build_nested_tools(self) -> List:
        from app.domain.services.tools.shell import ShellToolkit
        from app.domain.services.tools.browser import BrowserToolkit
        from app.domain.services.tools.file import FileToolkit
        from app.domain.services.tools.image import ImageToolkit
        from app.domain.services.tools.search import SearchToolkit

        tools = [
            ShellToolkit(self._sandbox),
            BrowserToolkit(self._browser),
            FileToolkit(self._sandbox),
            ImageToolkit(self._sandbox),
            self._mcp_tool,
        ]
        if self._search_engine:
            tools.append(SearchToolkit(self._search_engine))
        # Intentionally NO MessageToolkit (cannot ask the user) and NO
        # DelegateToolkit (no recursive nesting) — see module docstring.
        return tools

    @tool(parse_docstring=True)
    async def task_delegate(
        self,
        goal: str,
        expected_output: str,
    ) -> ToolResult:
        """Delegate ONE self-contained subtask to a sub-agent that works autonomously in the same workspace and returns a final report. Use for parallelisable chunks of heavy work (e.g. research one topic while you work on another, or scan many files) — NOT for tiny 1-2 call lookups you can do yourself. The sub-agent shares your sandbox, browser and files, but cannot ask the user questions.

        Args:
            goal: Complete, standalone description of the subtask — everything the sub-agent needs, since it does NOT see this conversation.
            expected_output: What the final report must contain (e.g. "3 verified sources with dates and key numbers", or "list of files changed and test results").
        """
        from app.domain.services.agents.execution import ExecutionAgent
        from app.domain.services.prompts.execution import EXECUTION_SYSTEM_PROMPT

        try:
            nested_id = f"{self._agent_id}-nested-{uuid.uuid4().hex[:8]}"
            nested = ExecutionAgent(
                agent_id=nested_id,
                agent_repository=_TransientAgentRepository(),
                tools=self._build_nested_tools(),
            )
            nested.max_iterations = _NESTED_MAX_ITERATIONS
            nested.system_prompt = (
                self._base_prompt
                + EXECUTION_SYSTEM_PROMPT
                + "\n\n<sub_agent>\n"
                "You are a focused SUB-AGENT handling exactly one subtask "
                "inside an ongoing parent task. Rules:\n"
                "- Work fully autonomously. You CANNOT ask the user "
                "anything — make sensible decisions yourself.\n"
                "- You share the parent's sandbox, browser and files; "
                "everything you create is visible to the parent.\n"
                "- Do exactly the subtask, nothing broader. No "
                "message_notify_user calls — the parent narrates for the "
                "user.\n"
                "- Finish with a final message that IS your report: "
                "complete, concrete, self-contained (facts, numbers, paths, "
                "outcomes), in the user's language. The parent only sees "
                "that report, so it must carry everything that matters.\n"
                "</sub_agent>"
            )

            context_note = ""
            try:
                if self._parent_context_provider:
                    digest = (self._parent_context_provider() or "").strip()
                    if digest:
                        context_note = (
                            "\n\n[Parent task context — for orientation "
                            "only; do not redo this work]\n"
                            f"{digest[:4000]}"
                        )
            except Exception:
                logger.debug("parent context digest unavailable", exc_info=True)

            request = (
                f"SUBTASK: {goal.strip()}\n\n"
                f"REQUIRED REPORT CONTENTS: {expected_output.strip()}"
                f"{context_note}"
            )

            # Drive the bounded tool loop; events are intentionally swallowed
            # (the parent's own narration covers progress; the delegate tool
            # event itself marks the work in the timeline).
            async for _event in nested.execute(request):
                pass

            report = self._extract_final_report(nested)
            logger.info(
                "Nested executor %s finished subtask (%d chars report)",
                nested_id, len(report),
            )
            return ToolResult(
                success=True,
                message=report[:_REPORT_MAX_CHARS],
                data={"report": report, "sub_agent": nested_id},
            )
        except Exception as exc:
            logger.warning("task_delegate failed: %s", exc, exc_info=True)
            return ToolResult(
                success=False,
                message=(
                    f"The sub-agent could not complete the subtask: {exc}. "
                    "Do the work yourself with your own tools instead."
                ),
            )

    def _extract_final_report(self, nested) -> str:
        """Pull the sub-agent's final answer from its memory.

        The tool loop ends when the model stops issuing tool calls — that
        last AIMessage is the report. Falls back to a graceful summary so
        the parent never receives an empty string.
        """
        try:
            messages = nested.memory.get_messages() if nested.memory else []
        except Exception:
            messages = []
        for message in reversed(messages):
            if isinstance(message, LCAIMessage):
                content = message.content
                if isinstance(content, list):
                    content = "".join(
                        b.get("text", "") for b in content if isinstance(b, dict)
                    )
                text = (content or "").strip()
                if text:
                    return text
        return (
            "The sub-agent finished without producing a final report. "
            "Check the workspace yourself and complete the remaining work."
        )
