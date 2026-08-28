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
import copy


# ── Official Manus ``brief`` support ─────────────────────────────────────
# The timeline shows a natural-language action label (tool ``brief``) instead
# of raw file paths / shell commands. The model must supply it with every
# executable tool call; the agent strips it before invoking the tool impl.
BRIEF_PARAM_SCHEMA: Dict[str, Any] = {
    "type": "string",
    "description": (
        "Short user-facing description of this action in the user's language "
        "(what you are doing), e.g. 'Menulis kode contoh Python' or 'Run the "
        "example and capture output'. Do not put file paths or raw shell "
        "commands here."
    ),
}

# Soft tools whose output is already user-facing narration — no brief needed.
_BRIEF_EXEMPT_TOOLKITS = {"message"}


def _with_brief_parameter(parameters: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Copy an OpenAI parameters schema and require a ``brief`` property."""
    params: Dict[str, Any] = copy.deepcopy(parameters) if parameters else {
        "type": "object",
        "properties": {},
    }
    if params.get("type") != "object":
        params["type"] = "object"
    props = params.setdefault("properties", {})
    if not isinstance(props, dict):
        props = {}
        params["properties"] = props
    if "brief" not in props:
        props["brief"] = dict(BRIEF_PARAM_SCHEMA)
    required = params.setdefault("required", [])
    if isinstance(required, list) and "brief" not in required:
        required.append("brief")
    return params


def _take_brief(args: Optional[Dict[str, Any]]) -> tuple:
    """Split ``brief`` from tool-call args (brief is UI-only, not for tool impl)."""
    clean = dict(args or {})
    raw = clean.pop("brief", None)
    if raw is None:
        return None, clean
    if isinstance(raw, str):
        text = raw.strip()
        return (text or None), clean
    text = str(raw).strip()
    return (text or None), clean


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


# Provider validation-glitch signatures — HTTP 400s that are in fact transient
# (a plain re-send succeeds). Observed on NVIDIA NIM / OpenRouter free models.
_GLITCH_SIGNATURES = (
    "cannot be empty",
    "must not be empty",
    "at least one message is required",
    "field is required",
    "must be provided",
)


def _is_validation_glitch(exc: Exception) -> bool:
    """True when a 400 error matches a known transient validation glitch."""
    text = str(exc).lower()
    return any(sig in text for sig in _GLITCH_SIGNATURES)


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

    # ── Patient rate-limit retry ─────────────────────────────────────────────
    # Rate limits are usually SHORT per-provider windows (per-minute quotas).
    # Killing a whole task after ~2.5 min of 429s wastes work that auto-resumes
    # a few minutes later. Limit errors therefore get an EXTENDED attempt
    # budget with capped back-off (~11 min total patience with the default
    # max_retries=6: 5+10+20+40+80+90*6 = 695s) and provider rotation, so the
    # task resumes automatically when the window clears.
    _RATE_LIMIT_EXTRA_ATTEMPTS: int = 6
    _RATE_LIMIT_WAIT_CAP: float = 90.0
    # User-facing "waiting" notice: only announce waits >= this many seconds,
    # and at most once per throttle window (avoids chat spam while retrying).
    _RATE_LIMIT_NOTICE_MIN_WAIT: float = 20.0
    _RATE_LIMIT_NOTICE_THROTTLE: float = 180.0

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
        # Remember the primary provider so limit-error rotation can alternate
        # primary <-> fallback (each provider gets time to clear its window).
        self._primary_model = self._model
        self._primary_auth_failed = False
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
        # Optional async callback ``rate_limit_notice(text)`` — set by the task
        # runner so the user SEES that the agent is patiently waiting out a
        # provider rate limit instead of staring at a frozen screen.
        self.rate_limit_notice: Optional[Any] = None
        self._last_rate_limit_notice_ts: float = 0.0

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

    def _switch_to_primary_model(self, reason: str) -> bool:
        """Rotate BACK to the primary provider (rate-limit recovery).

        Used by the patient 429 loop: rate-limit windows are per-provider, so
        alternating primary <-> fallback gives each pool time to clear instead
        of hammering one provider against a wall. Never rotates back to a
        primary that failed with an AUTH error — that key is simply invalid.
        """
        if self._primary_model is None or self._primary_auth_failed:
            return False
        if not self._using_fallback:
            return False
        self._model = self._primary_model
        self._using_fallback = False
        self._json_output_parser = RetryWithErrorOutputParser.from_llm(
            parser=JsonOutputParser(),
            llm=self._model,
            max_retries=self.max_retries,
        )
        logger.warning(
            "Agent %s rotating BACK to primary model provider: %s",
            self._agent_id, reason,
        )
        return True

    def _rotate_provider_for_limit(self, reason: str) -> bool:
        """On a rate-limit error, alternate primary <-> fallback providers.

        Balance/quota exhaustion (HTTP 402 "Insufficient balance", daily
        free-tier caps) does NOT clear on a minutes-scale window, so once we
        are on the fallback we STAY there for the rest of the run — rotating
        back to a dead key would only burn the retry budget. Time-window rate
        limits (429) still alternate: the primary's window may clear while we
        borrow the fallback.
        """
        if not self._using_fallback:
            return self._switch_to_fallback_model(reason)
        _sticky = any(
            kw in reason.lower()
            for kw in ("insufficient", "quota", "credit", "balance", "402", "billing")
        )
        if _sticky:
            logger.info(
                "Staying on fallback provider (primary balance/quota exhausted): %s",
                reason[:120],
            )
            return False
        return self._switch_to_primary_model(reason)

    def _limit_retry_wait(self, attempt: int) -> float:
        """Back-off seconds before limit-error retry #``attempt``.

        Exponential from ``retry_interval`` but capped at
        ``_RATE_LIMIT_WAIT_CAP`` so the TOTAL patience across the extended
        limit budget stays bounded (~11 min with defaults) instead of growing
        without limit. Shared by the ask-with-messages loop and the streaming
        loop so both paths wait on exactly the same schedule.
        """
        return min(self.retry_interval * (2 ** attempt), self._RATE_LIMIT_WAIT_CAP)

    def _rate_limit_budget(self) -> int:
        """Total attempts allowed while a provider is rate-limiting us."""
        return self.max_retries + self._RATE_LIMIT_EXTRA_ATTEMPTS

    async def _notify_rate_limit_wait(self, wait_seconds: float) -> None:
        """Tell the user the agent is patiently waiting out a rate limit.

        Without this, a multi-minute provider rate limit looks exactly like a
        frozen/dead task. Throttled so a long retry sequence emits at most one
        notice every few minutes.
        """
        import time as _time

        cb = self.rate_limit_notice
        if cb is None or wait_seconds < self._RATE_LIMIT_NOTICE_MIN_WAIT:
            return
        now = _time.monotonic()
        if (
            self._last_rate_limit_notice_ts
            and now - self._last_rate_limit_notice_ts < self._RATE_LIMIT_NOTICE_THROTTLE
        ):
            return
        self._last_rate_limit_notice_ts = now
        text = (
            "Provider model sedang membatasi permintaan (429) — saya menunggu "
            f"±{int(wait_seconds)} detik dan akan melanjutkan otomatis, tugas "
            "tidak hilang. / The model provider is rate-limiting requests — "
            f"waiting about {int(wait_seconds)}s and resuming automatically; "
            "your task is not lost."
        )
        try:
            result = cb(text)
            if asyncio.iscoroutine(result) or asyncio.isfuture(result):
                await result
        except Exception:
            logger.debug("rate-limit notice callback failed", exc_info=True)

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

    def _tools_with_brief(self) -> List[Any]:
        """OpenAI tool schemas with the required ``brief`` parameter injected.

        The model supplies a short natural-language label with every call; the
        agent strips it in ``execute()`` before the tool implementation runs.
        Soft narration tools (message toolkit) are exempt. Returns a mix of
        dicts and Tools — ``bind_tools`` accepts both.
        """
        try:
            from langchain_core.utils.function_calling import convert_to_openai_tool
        except Exception:
            return self.get_tools()
        schemas: List[Any] = []
        for tool in self.get_tools():
            toolkit_name = getattr(tool, "toolkit", None)
            toolkit_name = getattr(toolkit_name, "name", "") or ""
            if toolkit_name in _BRIEF_EXEMPT_TOOLKITS:
                schemas.append(tool)
                continue
            try:
                schema = convert_to_openai_tool(tool)
                function = schema.get("function", {})
                function["parameters"] = _with_brief_parameter(function.get("parameters"))
                schemas.append(schema)
            except Exception:
                # Fall back to the raw tool if schema conversion fails.
                schemas.append(tool)
        return schemas

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

        HTTP 402 "Insufficient balance" (free-tier exhaustion) arrives the same
        way and is included: the caller's limit-error branch rotates to the
        fallback provider, so the task keeps running instead of dying.
        """
        if not isinstance(exc, ValueError) or not exc.args:
            return False
        payload = exc.args[0]
        if not isinstance(payload, dict):
            return False
        code = payload.get("code")
        if (
            code == 429
            or code == 402
            or (isinstance(code, int) and 500 <= code < 600)
        ):
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
                "insufficient balance",
                "insufficient",
                "quota",
                "credit",
            )
        )

    async def execute(self, request: Union[str, list], format: Optional[str] = None) -> AsyncGenerator[BaseEvent, None]:
        format = format or self.format
        message = await self.ask(request, format)
        for iteration in range(self.max_iterations):
            if not message.tool_calls:
                break
            # ── Content narration → visible progress line ──────────────────
            # Models like MiniMax M3 naturally "think out loud" in the
            # AIMessage content alongside tool calls ("Saya akan memeriksa
            # dulu konfigurasinya…"). That text was previously DISCARDED here
            # — the chat went silent even though the model WAS narrating
            # (user complaint: "kok hening / kaku"). Emit it as an
            # is_progress MessageEvent BEFORE this round's tool events, so
            # the user hears the intent BEFORE the action executes. Downstream
            # consumers that expect the FINAL result keep working: they only
            # treat non-progress MessageEvents as the completion payload.
            _narration = message.content
            if isinstance(_narration, list):
                _narration = "".join(
                    b.get("text", "") for b in _narration if isinstance(b, dict)
                )
            _narration = (_narration or "").strip()
            if _narration and not _narration.startswith("{"):
                yield MessageEvent(
                    message=_narration[:600],
                    is_progress=True,
                    role="assistant",
                )
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

                # Official Manus ``brief``: the model supplies a short NL label
                # with the call. Strip it here so the tool implementation never
                # sees an unexpected kwarg, then carry it on both ToolEvents.
                brief, clean_args = _take_brief(function_args)
                function_args = clean_args
                tool_call["args"] = clean_args

                # Generate event before tool call
                yield ToolEvent(
                    status=ToolStatus.CALLING,
                    tool_call_id=tool_call_id,
                    tool_name=tool.toolkit.name,
                    function_name=function_name,
                    function_args=function_args,
                    brief=brief,
                )

                tool_result = await self.invoke_tool(tool, tool_call)

                # Generate event after tool call
                yield ToolEvent(
                    status=ToolStatus.CALLED,
                    tool_call_id=tool_call_id,
                    tool_name=tool.toolkit.name,
                    function_name=function_name,
                    function_args=function_args,
                    function_result=tool_result.artifact,
                    brief=brief,
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
                .bind_tools(self._tools_with_brief())
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
        attempt = 0
        while True:
            try:
                message: AIMessage = await chain.ainvoke(context)
                break
            except ToolCallParseError as e:
                if attempt >= self.max_retries - 1:
                    raise
                logger.warning(
                    "Attempt %d/%d: tool call JSON repair failed, retrying model",
                    attempt + 1, self.max_retries,
                )
                if attempt > 0:
                    # Stage 5 (RetryWithErrorOutputParser style): add error feedback.
                    context = e.make_retry_context(context)
                attempt += 1
            except (openai.AuthenticationError, openai.PermissionDeniedError) as e:
                # Invalid / exhausted primary key — retrying the same provider
                # is pointless. Switch to the fallback provider when one is
                # configured; otherwise surface the error immediately.
                if not self._using_fallback:
                    self._primary_auth_failed = True
                if self._switch_to_fallback_model(str(e)):
                    chain = _build_chain()
                    continue
                raise
            except _TRANSIENT_API_ERRORS as e:
                # Rate limits get the patient treatment: rotate provider (free —
                # limit windows are per-provider, the OTHER provider may serve
                # right away), then wait with capped back-off under an EXTENDED
                # attempt budget so the task auto-resumes when the window
                # clears instead of dying with a 429 error.
                _is_limit = self._is_limit_error(e)
                _budget = (
                    self._rate_limit_budget() if _is_limit else self.max_retries
                )
                if attempt >= _budget - 1:
                    logger.error(
                        "LLM API error after %d attempts, giving up: %s",
                        attempt + 1, e,
                    )
                    raise
                if _is_limit:
                    if self._rotate_provider_for_limit(str(e)):
                        chain = _build_chain()
                    wait = self._limit_retry_wait(attempt)
                    await self._notify_rate_limit_wait(wait)
                else:
                    wait = self.retry_interval * (2 ** attempt)
                logger.warning(
                    "Transient LLM API error (attempt %d/%d), retrying in %.1fs: %s",
                    attempt + 1, _budget, wait, type(e).__name__,
                )
                attempt += 1
                await asyncio.sleep(wait)
            except ValueError as e:
                # OpenRouter-style "HTTP 200 + error body" provider failures are
                # surfaced by langchain-openai as a bare ValueError — retry them
                # exactly like the transient API errors above when they carry a
                # transient code (429 / 402 / 5xx / rate-limit wording). Limit-
                # style payloads ("Insufficient balance", quota, credit) get the
                # provider-rotation treatment so the task survives key
                # exhaustion instead of dying mid-run.
                _is_limit = self._is_limit_error(e)
                if not (_is_limit or self._transient_provider_error(e)):
                    raise
                _budget = (
                    self._rate_limit_budget() if _is_limit else self.max_retries
                )
                if attempt >= _budget - 1:
                    logger.error(
                        "Provider error after %d attempts, giving up: %s",
                        attempt + 1, e,
                    )
                    raise
                if _is_limit:
                    if self._rotate_provider_for_limit(str(e)):
                        chain = _build_chain()
                    wait = self._limit_retry_wait(attempt)
                    await self._notify_rate_limit_wait(wait)
                else:
                    wait = self.retry_interval * (2 ** attempt)
                logger.warning(
                    "Transient provider error in 200-response body "
                    "(attempt %d/%d), retrying in %.1fs: %s",
                    attempt + 1, _budget, wait, e,
                )
                attempt += 1
                await asyncio.sleep(wait)
            except openai.NotFoundError as e:
                # OpenRouter free-tier models intermittently report
                # "No endpoints found" (HTTP 404) while the provider pool
                # recycles — transient in practice, so retry with backoff.
                if "no endpoints found" not in str(e).lower():
                    raise
                if attempt >= self.max_retries - 1:
                    logger.error(
                        "Provider endpoints unavailable after %d attempts: %s",
                        attempt + 1, e,
                    )
                    raise
                wait = self.retry_interval * (2 ** attempt)
                logger.warning(
                    "Provider endpoints unavailable (attempt %d/%d), "
                    "retrying in %.1fs: %s",
                    attempt + 1, self.max_retries, wait, e,
                )
                attempt += 1
                await asyncio.sleep(wait)
            except openai.BadRequestError as e:
                # Transient provider validation glitches: NVIDIA NIM /
                # OpenRouter-routed free models intermittently answer a
                # perfectly valid request with HTTP 400
                # "The 'messages' field cannot be empty" (observed in
                # production with a non-empty context). Re-sending the same
                # request works, so retry briefly instead of killing the task.
                # Any OTHER 400 (bad schema, bad params) still raises at once.
                _glitch = _is_validation_glitch(e)
                if not _glitch or attempt >= 2:
                    raise
                wait = 2.0 * (attempt + 1)
                logger.warning(
                    "Transient 400 validation glitch (attempt %d/3), "
                    "retrying same request in %.1fs: %s",
                    attempt + 1, wait, str(e)[:200],
                )
                attempt += 1
                await asyncio.sleep(wait)
            except openai.APIStatusError as e:
                # HTTP 402 "Insufficient balance" (OpenRouter free-tier
                # exhaustion) is NOT mapped to a specific SDK exception, so
                # it used to fall through every clause above and kill the
                # whole task mid-run. Treat limit/quota-style status errors
                # like the transient path: rotate to the fallback provider
                # (free, instant) and retry on the patient schedule. Any
                # other status error re-raises unchanged.
                _is_limit = self._is_limit_error(e)
                _status = getattr(e, "status_code", None)
                if not (_is_limit or _status == 402):
                    raise
                _budget = self._rate_limit_budget()
                if attempt >= _budget - 1:
                    logger.error(
                        "Provider status error after %d attempts, giving up: %s",
                        attempt + 1, e,
                    )
                    raise
                if self._rotate_provider_for_limit(str(e)):
                    chain = _build_chain()
                wait = self._limit_retry_wait(attempt)
                await self._notify_rate_limit_wait(wait)
                logger.warning(
                    "Provider limit/status error %s (attempt %d/%d), "
                    "rotated provider, retrying in %.1fs: %s",
                    _status, attempt + 1, _budget, wait, e,
                )
                attempt += 1
                await asyncio.sleep(wait)
        logger.debug(f"Response from model: {message}")

        await self._add_to_memory([message])
        return message

    async def astream_text_with_fallback(self, messages) -> str:
        """Collect the full streamed text from the model.

        On a limit/quota/auth error the request fails BEFORE any chunk is
        produced, so it is safe to rotate providers and retry. Used by the
        direct-astream call sites (planner acknowledgement, executor summary)
        that bypass ask_with_messages.

        Rate limits use the same PATIENT schedule as ask_with_messages:
        provider rotation + capped back-off + extended budget, so a long task
        summarising at a rate-limit window auto-resumes instead of dying with
        a 429 error after two attempts.
        """
        attempt = 0
        while True:
            try:
                parts: list = []
                async for chunk in self._model.astream(messages):
                    text = chunk.content if isinstance(chunk.content, str) else ""
                    if text:
                        parts.append(text)
                return "".join(parts)
            except openai.BadRequestError as e:
                # Transient provider validation glitch — re-send works.
                if not _is_validation_glitch(e) or attempt >= 2:
                    raise
                wait = 2.0 * (attempt + 1)
                logger.warning(
                    "Transient 400 validation glitch while streaming "
                    "(attempt %d/3), retrying in %.1fs: %s",
                    attempt + 1, wait, str(e)[:200],
                )
                attempt += 1
                await asyncio.sleep(wait)
            except Exception as e:
                _is_limit = self._is_limit_error(e)
                _budget = (
                    self._rate_limit_budget() if _is_limit else self.max_retries
                )
                if attempt >= _budget - 1:
                    raise
                if _is_limit:
                    # Rotate provider immediately (free) — per-provider limit
                    # windows mean the OTHER provider may serve right away —
                    # then wait on the same capped schedule as the tool loop.
                    self._rotate_provider_for_limit(str(e))
                    wait = self._limit_retry_wait(attempt)
                    await self._notify_rate_limit_wait(wait)
                    logger.warning(
                        "Rate limit while streaming (attempt %d/%d), "
                        "retrying in %.1fs: %s",
                        attempt + 1, _budget, wait, e,
                    )
                    attempt += 1
                    await asyncio.sleep(wait)
                    continue
                # Transient non-limit errors (5xx / network) — short retry.
                _transient = isinstance(
                    e,
                    (openai.InternalServerError, openai.APIConnectionError,
                     openai.APITimeoutError),
                ) or self._transient_provider_error(e)
                if _transient:
                    wait = self.retry_interval * (2 ** attempt)
                    logger.warning(
                        "Transient stream error (attempt %d/%d), retrying in %.1fs: %s",
                        attempt + 1, self.max_retries, wait, e,
                    )
                    attempt += 1
                    await asyncio.sleep(wait)
                    continue
                raise
        return ""

    async def astream_chunks_with_fallback(self, messages) -> AsyncGenerator[str, None]:
        """Yield streamed text chunks LIVE (token-by-token) with the same
        provider-rotation fallback as astream_text_with_fallback.

        Used for the fast first-response acknowledgement: the caller forwards
        each yielded chunk to the client immediately, so the user sees text in
        ~1-2 s instead of waiting for the full response.

        Fallback safety: limit/auth errors fail BEFORE any chunk is produced,
        so rotation + retry is only allowed while nothing has been surfaced.
        If the stream dies mid-flight after chunks were already yielded, we
        simply stop — retrying would duplicate visible text in the chat.
        """
        attempt = 0
        while True:
            emitted = False
            try:
                async for chunk in self._model.astream(messages):
                    text = chunk.content if isinstance(chunk.content, str) else ""
                    if text:
                        emitted = True
                        yield text
                return
            except Exception as e:
                if emitted:
                    logger.warning(
                        "Live stream died mid-flight after chunks were emitted; "
                        "keeping partial text instead of duplicating: %s",
                        e,
                    )
                    return
                if isinstance(e, openai.BadRequestError) and _is_validation_glitch(e) and attempt < 2:
                    wait = 2.0 * (attempt + 1)
                    logger.warning(
                        "Transient 400 validation glitch in live stream "
                        "(attempt %d/3), retrying in %.1fs: %s",
                        attempt + 1, wait, str(e)[:200],
                    )
                    attempt += 1
                    await asyncio.sleep(wait)
                    continue
                _is_limit = self._is_limit_error(e)
                _budget = (
                    self._rate_limit_budget() if _is_limit else self.max_retries
                )
                if attempt >= _budget - 1:
                    raise
                if _is_limit:
                    self._rotate_provider_for_limit(str(e))
                    wait = self._limit_retry_wait(attempt)
                    await self._notify_rate_limit_wait(wait)
                    logger.warning(
                        "Rate limit while live streaming (attempt %d/%d), "
                        "retrying in %.1fs: %s",
                        attempt + 1, _budget, wait, e,
                    )
                    attempt += 1
                    await asyncio.sleep(wait)
                    continue
                # Transient non-limit errors (5xx / network) — short retry.
                _transient = isinstance(
                    e,
                    (openai.InternalServerError, openai.APIConnectionError,
                     openai.APITimeoutError),
                ) or self._transient_provider_error(e)
                if _transient:
                    wait = self.retry_interval * (2 ** attempt)
                    logger.warning(
                        "Transient live stream error (attempt %d/%d), retrying in %.1fs: %s",
                        attempt + 1, self.max_retries, wait, e,
                    )
                    attempt += 1
                    await asyncio.sleep(wait)
                    continue
                raise

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
