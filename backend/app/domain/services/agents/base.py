import logging
import asyncio
import uuid
import httpx
from abc import ABC
from typing import List, Dict, Any, Optional, AsyncGenerator, Union
from app.domain.models.message import Message
from app.domain.services.tools.base import BaseToolkit
from app.domain.models.event import (
    BaseEvent,
    ToolEvent,
    ToolStatus,
    ErrorEvent,
    MessageEvent,
)
from app.domain.repositories.agent_repository import AgentRepository
from langchain.chat_models import init_chat_model
from langchain_classic.output_parsers.retry import RetryWithErrorOutputParser
from langchain_core.output_parsers import JsonOutputParser
from langchain_core.prompts import PromptTemplate
from app.core.config import get_settings, get_fallback_model_config
from langchain.messages import AIMessage, HumanMessage, ToolCall, ToolMessage, SystemMessage
from app.domain.services.tools.base import Tool
from app.domain.utils.robust_json_parser import RobustJsonParser, ToolCallParseError
import openai


def _build_chat_model(prefer_fallback: bool = False):
    """Create the chat model for an agent.

    prefer_fallback=False → the primary provider from settings.
    prefer_fallback=True  → the fallback provider (z.ai internal API or
                            FALLBACK_* env config); returns None when no
                            fallback is configured.
    """
    settings = get_settings()
    if prefer_fallback:
        cfg = get_fallback_model_config()
        if not cfg:
            return None
        return init_chat_model(
            model=cfg["model_name"],
            model_provider="openai",
            temperature=settings.temperature,
            max_tokens=settings.max_tokens,
            base_url=cfg["api_base"],
            openai_api_key=cfg["api_key"],
            default_headers=cfg["extra_headers"],
            extra_body={"thinking": {"type": "disabled"}},
        )
    kwargs = dict(
        model=settings.model_name,
        model_provider=settings.model_provider,
        temperature=settings.temperature,
        max_tokens=settings.max_tokens,
        base_url=settings.api_base,
    )
    # Pass the API key explicitly — env-var fallback (OPENAI_API_KEY) is
    # not reliable when credentials are only present in the .env file.
    if settings.api_key:
        if settings.model_provider in ("openai",):
            kwargs["openai_api_key"] = settings.api_key
        else:
            kwargs["api_key"] = settings.api_key
    if settings.extra_headers:
        kwargs["default_headers"] = settings.extra_headers
    if settings.api_base:
        verify = settings.ssl_verify
        kwargs["http_client"] = httpx.Client(verify=verify)
        kwargs["http_async_client"] = httpx.AsyncClient(verify=verify)
    return init_chat_model(**kwargs)


logger = logging.getLogger(__name__)
class BaseAgent(ABC):
    """
    Base agent class, defining the basic behavior of the agent
    """

    name: str = ""
    system_prompt: str = ""
    format: Optional[str] = None
    max_iterations: int = 100
    max_retries: int = 6
    retry_interval: float = 5.0
    tool_choice: Optional[str] = None

    _JSON_PARSE_PROMPT = PromptTemplate.from_template(
        "Extract or repair the JSON from the following LLM output.\n\n{input}"
    )

    def __init__(
        self,
        agent_id: str,
        agent_repository: AgentRepository,
        tools: List[BaseToolkit] = []
    ):
        settings = get_settings()
        self._agent_id = agent_id
        self._repository = agent_repository
        self._model = _build_chat_model(prefer_fallback=False)
        self._json_output_parser = RetryWithErrorOutputParser.from_llm(
            parser=JsonOutputParser(),
            llm=self._model,
            max_retries=self.max_retries,
        )
        self.toolkits = tools
        self.memory = None
        # Fallback provider state — switched on automatically when the primary
        # provider hits rate limits / quota / auth errors.
        self._using_fallback = False

    def _switch_to_fallback_model(self, reason: str) -> bool:
        """Swap the agent's model to the fallback provider. Returns success."""
        if self._using_fallback:
            return False
        fallback = _build_chat_model(prefer_fallback=True)
        if fallback is None:
            return False
        self._model = fallback
        self._using_fallback = True
        self._json_output_parser = RetryWithErrorOutputParser.from_llm(
            parser=JsonOutputParser(),
            llm=self._model,
            max_retries=self.max_retries,
        )
        logger.warning(
            "Agent %s switching to FALLBACK model provider (%s): %s",
            self._agent_id, type(self._model).__name__, reason,
        )
        return True

    @staticmethod
    def _is_limit_error(exc: Exception) -> bool:
        """Whether an API error means the primary provider's key is exhausted
        (rate limit / quota / credits / auth) and a fallback should be used."""
        if isinstance(exc, openai.RateLimitError):
            return True
        if isinstance(
            exc,
            (openai.AuthenticationError, openai.PermissionDeniedError),
        ):
            return True
        msg = str(exc).lower()
        return any(
            keyword in msg
            for keyword in (
                "rate limit",
                "quota",
                "credit",
                "insufficient",
                "exceeded your current quota",
                "billing",
                "limit reached",
            )
        )

    async def _parse_json(self, text: str) -> dict:
        """Parse JSON from LLM output using RetryWithErrorOutputParser."""
        prompt_value = self._JSON_PARSE_PROMPT.format_prompt(input=text)
        return await self._json_output_parser.aparse_with_prompt(text, prompt_value)
    
    @staticmethod
    def _normalize_tool_name(name: str) -> str:
        """Clean a tool name polluted with model-generation junk.

        Free-tier models occasionally emit tool calls whose NAME field carries
        fragments of the surrounding syntax — observed in production:
        ``"browser_view\\n</parameter"`` (a stray XML closing tag glued onto
        the function name), names wrapped in stray quotes, or names followed
        by markdown/xml separators. Strategy: keep the first line only, cut at
        the first XML-ish character, strip quotes and whitespace.
        """
        if not name:
            return ""
        raw = str(name)
        # First non-empty line only — junk always arrives after a newline.
        first_line = next(
            (ln.strip() for ln in raw.splitlines() if ln.strip()), ""
        )
        # Cut at the first XML/markdown separator character if present.
        for sep in ("<", ">", "`", "|"):
            idx = first_line.find(sep)
            if idx > 0:
                first_line = first_line[:idx].strip()
        return first_line.strip("'\" \t").strip()

    def get_tool(self, name: str) -> Optional[Tool]:
        """Get specified tool.

        Resolution order:
        1. Exact name match.
        2. Normalized name (handles junk like ``"browser_view\\n</parameter"``).
        3. Boundary-aware containment: a registered tool name appearing inside
           the polluted name as a whole token (longest match wins).
        """
        import re as _re

        # 1. Exact match.
        for toolkit in self.toolkits:
            tool = toolkit.get_tool(name)
            if tool:
                return tool

        raw = str(name or "")
        if not raw.strip():
            return None

        # 2. Normalized name match.
        normalized = self._normalize_tool_name(raw)
        if normalized and normalized != raw:
            for toolkit in self.toolkits:
                tool = toolkit.get_tool(normalized)
                if tool:
                    logger.info(
                        "Resolved polluted tool name %r -> %r", raw, tool.name
                    )
                    return tool

        # 3. Boundary-aware containment (last resort): the polluted string
        #    contains a registered tool name as a whole identifier.
        candidates = sorted(
            (t for tk in self.toolkits for t in tk.get_tools()),
            key=lambda t: -len(t.name),
        )
        for tool in candidates:
            if tool.name and _re.search(
                rf"(?<![A-Za-z0-9_]){_re.escape(tool.name)}(?![A-Za-z0-9_])",
                raw,
            ):
                logger.info(
                    "Resolved polluted tool name %r -> %r (containment)",
                    raw, tool.name,
                )
                return tool
        return None

    def get_tools(self) -> List[Tool]:
        """Get all available tools list"""
        return [tool for toolkit in self.toolkits for tool in toolkit.get_tools()]

    async def invoke_tool(self, tool: Tool, tool_call: ToolCall) -> ToolMessage:
        """Invoke specified tool, with retry mechanism."""
        retries = 0
        while retries <= self.max_retries:
            try:
                return await tool.ainvoke(tool_call)
            except Exception as e:
                last_error = str(e)
                retries += 1
                if retries <= self.max_retries:
                    await asyncio.sleep(self.retry_interval)
                else:
                    logger.exception(f"Tool execution failed, {tool_call['name']}, {tool_call['args']}")
                    break

        return ToolMessage(tool_call_id=tool_call["id"], name=tool.name, content=last_error)
    
    # Compact browser tool results in memory every this many tool-call rounds
    # within a single step to prevent "Payload Too Large" on complex pages.
    _COMPACT_EVERY_N_ITERATIONS = 10

    @staticmethod
    def _transient_provider_error(exc: Exception) -> bool:
        """Detect transient provider errors that arrive as a bare ValueError.

        OpenRouter (and some OpenAI-compatible gateways) occasionally return
        HTTP 200 with an ``{"error": {"message": ..., "code": 429/5xx}}`` body.
        The OpenAI SDK does not raise for HTTP 200, so langchain-openai surfaces
        the payload as ``ValueError({'message': ..., 'code': ...})`` — which the
        transient-retry loop below would otherwise never catch, crashing the
        whole agent task on a simple rate limit.
        """
        if not isinstance(exc, ValueError) or not exc.args:
            return False
        payload = exc.args[0]
        if not isinstance(payload, dict):
            return False
        code = payload.get("code")
        if code == 429 or (isinstance(code, int) and 500 <= code < 600):
            return True
        message = str(payload.get("message", "")).lower()
        return any(
            keyword in message
            for keyword in (
                "rate limit",
                "overloaded",
                "temporarily unavailable",
                "try again",
                "provider returned error",
                "no endpoints found",
            )
        )

    async def execute(self, request: Union[str, list], format: Optional[str] = None) -> AsyncGenerator[BaseEvent, None]:
        format = format or self.format
        message = await self.ask(request, format)
        for iteration in range(self.max_iterations):
            if not message.tool_calls:
                break
            tool_responses = []
            for tool_call in message.tool_calls:
                function_name = tool_call["name"]
                tool_call_id = tool_call["id"] = tool_call["id"] or str(uuid.uuid4())
                function_args = tool_call["args"]
                
                tool = self.get_tool(function_name)
                if not tool:
                    # The tool could not be resolved even after name
                    # normalization. Two things must happen:
                    #   a) the USER sees a clean single-line error (raw names
                    #      can contain newlines / XML junk), and
                    #   b) the MODEL receives a ToolMessage for this call —
                    #      otherwise the tool_calls list in the conversation
                    #      is left dangling without a matching ToolMessage,
                    #      which some providers reject with HTTP 400, and the
                    #      model never learns the call failed.
                    clean_name = self._normalize_tool_name(function_name) or str(function_name).splitlines()[0]
                    yield ErrorEvent(error=f"Unknown tool: {clean_name}")
                    available = ", ".join(t.name for t in self.get_tools())
                    tool_responses.append(ToolMessage(
                        tool_call_id=tool_call_id,
                        name=clean_name,
                        content=(
                            f"Error: the tool '{clean_name}' does not exist. "
                            f"Available tools: {available}. "
                            "Re-issue the action using one of the tools above "
                            "with the correct tool name."
                        ),
                    ))
                    continue

                # Canonicalise the name after resolution — a polluted name
                # (e.g. "browser_view\n</parameter") must not leak into
                # ToolEvents, the frontend, or the narration lookup tables.
                if function_name != tool.name:
                    logger.info(
                        "Canonicalised tool name %r -> %r",
                        function_name, tool.name,
                    )
                    function_name = tool.name
                    tool_call["name"] = tool.name

                # Generate event before tool call
                yield ToolEvent(
                    status=ToolStatus.CALLING,
                    tool_call_id=tool_call_id,
                    tool_name=tool.toolkit.name,
                    function_name=function_name,
                    function_args=function_args
                )

                tool_result = await self.invoke_tool(tool, tool_call)

                # Generate event after tool call
                yield ToolEvent(
                    status=ToolStatus.CALLED,
                    tool_call_id=tool_call_id,
                    tool_name=tool.toolkit.name,
                    function_name=function_name,
                    function_args=function_args,
                    function_result=tool_result.artifact
                )

                tool_responses.append(tool_result)

            # Periodically compact browser tool results mid-step to prevent
            # "Payload Too Large" errors on pages with hundreds of elements.
            if (iteration + 1) % self._COMPACT_EVERY_N_ITERATIONS == 0:
                logger.debug(f"Mid-step compact at iteration {iteration + 1}")
                await self.compact_memory()

            message = await self.ask_with_messages(tool_responses)
        else:
            yield ErrorEvent(error="Maximum iteration count reached, failed to complete the task")
        
        yield MessageEvent(message=message.content)
    
    async def _ensure_memory(self):
        if not self.memory:
            self.memory = await self._repository.get_memory(self._agent_id, self.name)
    
    async def _add_to_memory(self, messages: List[Dict[str, Any]]) -> None:
        """Update memory and save to repository"""
        await self._ensure_memory()
        if self.memory.empty:
            settings = get_settings()
            effective_prompt = self.system_prompt
            if settings.extend_system_message:
                effective_prompt = (
                    effective_prompt.rstrip()
                    + "\n\n"
                    + settings.extend_system_message.strip()
                )
            self.memory.add_message(SystemMessage(content=effective_prompt))
        self.memory.add_messages(messages)
        await self._repository.save_memory(self._agent_id, self.name, self.memory)
    
    async def _roll_back_memory(self) -> None:
        await self._ensure_memory()
        self.memory.roll_back()
        await self._repository.save_memory(self._agent_id, self.name, self.memory)

    async def ask_with_messages(self, messages: List[Dict[str, Any]], format: Optional[str] = None) -> AIMessage:
        await self._add_to_memory(messages)

        response_format = None
        if format:
            response_format = {"type": format}

        # Stage 1-3: model chain | RobustJsonParser repairs invalid tool call JSON.
        # Stages 4-5: outer retry loop handles cases that survive stages 1-3.
        def _build_chain():
            return (
                self._model
                .bind(response_format=response_format, tool_choice=self.tool_choice)
                .bind_tools(self.get_tools())
                | RobustJsonParser.from_llm(self._model)
            )

        chain = _build_chain()

        # Transient API errors that are safe to retry (5xx, network blips, rate limits).
        _TRANSIENT_API_ERRORS = (
            openai.InternalServerError,   # 500/502/503 from the provider
            openai.APIConnectionError,    # network-level failure
            openai.APITimeoutError,       # request timed out
            openai.RateLimitError,        # 429 – back off and retry
        )

        context = list(self.memory.get_messages())
        for attempt in range(self.max_retries):
            try:
                message: AIMessage = await chain.ainvoke(context)
                break
            except ToolCallParseError as e:
                if attempt == self.max_retries - 1:
                    raise
                logger.warning(
                    "Attempt %d/%d: tool call JSON repair failed, retrying model",
                    attempt + 1, self.max_retries,
                )
                if attempt == 0:
                    # Stage 4 (RetryOutputParser style): silent retry, same context.
                    pass
                else:
                    # Stage 5 (RetryWithErrorOutputParser style): add error feedback.
                    context = e.make_retry_context(context)
            except (openai.AuthenticationError, openai.PermissionDeniedError) as e:
                # Invalid / exhausted primary key — retrying the same provider
                # is pointless. Switch to the fallback provider when one is
                # configured; otherwise surface the error immediately.
                if self._switch_to_fallback_model(str(e)):
                    chain = _build_chain()
                    continue
                raise
            except _TRANSIENT_API_ERRORS as e:
                # Primary key exhausted (rate limit / quota / auth) → switch to
                # the fallback provider immediately instead of burning retries
                # against a wall that backoff cannot fix.
                if self._is_limit_error(e) and self._switch_to_fallback_model(str(e)):
                    chain = _build_chain()
                    continue
                if attempt == self.max_retries - 1:
                    logger.error(
                        "LLM API error after %d attempts, giving up: %s",
                        self.max_retries, e,
                    )
                    raise
                wait = self.retry_interval * (2 ** attempt)  # exponential back-off
                logger.warning(
                    "Transient LLM API error (attempt %d/%d), retrying in %.1fs: %s",
                    attempt + 1, self.max_retries, wait, type(e).__name__,
                )
                await asyncio.sleep(wait)
            except ValueError as e:
                # OpenRouter-style "HTTP 200 + error body" provider failures are
                # surfaced by langchain-openai as a bare ValueError — retry them
                # exactly like the transient API errors above when they carry a
                # transient code (429 / 5xx / rate-limit wording).
                if not self._transient_provider_error(e):
                    raise
                if self._is_limit_error(e) and self._switch_to_fallback_model(str(e)):
                    chain = _build_chain()
                    continue
                if attempt == self.max_retries - 1:
                    logger.error(
                        "Provider error after %d attempts, giving up: %s",
                        self.max_retries, e,
                    )
                    raise
                wait = self.retry_interval * (2 ** attempt)
                logger.warning(
                    "Transient provider error in 200-response body "
                    "(attempt %d/%d), retrying in %.1fs: %s",
                    attempt + 1, self.max_retries, wait, e,
                )
                await asyncio.sleep(wait)
            except openai.NotFoundError as e:
                # OpenRouter free-tier models intermittently report
                # "No endpoints found" (HTTP 404) while the provider pool
                # recycles — transient in practice, so retry with backoff.
                if "no endpoints found" not in str(e).lower():
                    raise
                if attempt == self.max_retries - 1:
                    logger.error(
                        "Provider endpoints unavailable after %d attempts: %s",
                        self.max_retries, e,
                    )
                    raise
                wait = self.retry_interval * (2 ** attempt)
                logger.warning(
                    "Provider endpoints unavailable (attempt %d/%d), "
                    "retrying in %.1fs: %s",
                    attempt + 1, self.max_retries, wait, e,
                )
                await asyncio.sleep(wait)
        logger.debug(f"Response from model: {message}")

        await self._add_to_memory([message])
        return message

    async def astream_text_with_fallback(self, messages) -> str:
        """Collect the full streamed text from the model.

        On a limit/quota/auth error the request fails BEFORE any chunk is
        produced, so it is safe to switch to the fallback provider and
        retry the stream once. Used by the direct-astream call sites
        (planner acknowledgement, executor summary) that bypass
        ask_with_messages.
        """
        for attempt in (0, 1):
            try:
                parts: list = []
                async for chunk in self._model.astream(messages):
                    text = chunk.content if isinstance(chunk.content, str) else ""
                    if text:
                        parts.append(text)
                return "".join(parts)
            except Exception as e:
                if (
                    attempt == 0
                    and self._is_limit_error(e)
                    and self._switch_to_fallback_model(str(e))
                ):
                    continue
                raise
        return ""

    async def ask(self, request: Union[str, list], format: Optional[str] = None) -> AIMessage:
        return await self.ask_with_messages([
            HumanMessage(content=request)
        ], format)
    
    async def roll_back(self, message: Message):
        await self._ensure_memory()
        last_message = self.memory.get_last_message()
        if not last_message:
            return
        if last_message.type != "ai":
            return
        if not last_message.tool_calls:
            return
        tool_call = last_message.tool_calls[0]
        function_name = tool_call["name"]
        tool_call_id = tool_call["id"]
        if function_name == "message_ask_user":
            self.memory.add_message(ToolMessage(tool_call_id=tool_call_id, name=function_name, content=message))
        else:
            self.memory.roll_back()
        await self._repository.save_memory(self._agent_id, self.name, self.memory)
    
    async def compact_memory(self) -> None:
        await self._ensure_memory()
        self.memory.compact()
        await self._repository.save_memory(self._agent_id, self.name, self.memory)
