import logging
import asyncio
import itertools
import uuid
import httpx
from abc import ABC
from typing import List, Dict, Any, Optional, AsyncGenerator, Union
from app.domain.models.message import Message
from app.domain.services.tools.base import BaseToolkit
from app.domain.services.tools.base import Tool, cap_tool_content
from app.domain.models.tool_result import ToolResult
from app.domain.models.memory import compact_messages, drop_older_rounds
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
import json
import re as _re
import json as _json


# ── Legacy <function=NAME>...</function> syntax salvage ─────────────────
# Some providers (nemotron via certain gateways) occasionally emit the raw
# tool-call wire format as PLAIN TEXT inside AIMessage.content instead of
# parsed tool_calls. Observed live in session 6a935f37: the agent's FINAL
# answer was literally "\n<function=browser_click>\n<parameter=index>\n1016\n..."
# — leaked straight into the user's chat. These helpers parse that syntax
# back into real tool_calls (so the intended action actually executes), and
# strip any residue from final user-facing text.
_FUNCTION_BLOCK_RE = _re.compile(r"<function=(\w+)>(.*?)</function>", _re.DOTALL)
_PARAMETER_RE = _re.compile(r"<parameter=(\w+)>(.*?)</parameter>", _re.DOTALL)


# Qwen/Nemotron-style raw tool_call wire blocks. The streaming summarize
# layer occasionally emits an EMPTY residue block (two newlines between
# the tags) as the whole answer: the empty-prose guard then saw the TAGS
# as text and the final bubble shipped with no summary (live: sessions
# e6690289 / b00448, final message = the tags alone). Stripping the
# blocks, including an unclosed trailing one, lets the guard see the
# truth and fall back to the tool-loop, which produces the real answer.
_TOOL_CALL_BLOCK_RE = _re.compile(r'<tool_call>(.*?)</tool_call>', _re.DOTALL)
_TOOL_CALL_OPEN_RE = _re.compile(r'<tool_call>.*\Z', _re.DOTALL)


def _strip_function_syntax(text: str) -> str:
    """Remove raw tool-call wire-format blocks from user-facing text.

    Handles <function=NAME>...</function> (legacy) and raw Qwen-style
    tool_call blocks, including empty residue blocks and an unclosed
    trailing tag. Only the prose between the blocks survives.
    """
    if not text:
        return text
    if "<function=" in text:
        text = _FUNCTION_BLOCK_RE.sub("", text)
    if "<tool_" + "call>" in text:
        text = _TOOL_CALL_BLOCK_RE.sub("", text)
        text = _TOOL_CALL_OPEN_RE.sub("", text)
    return text.strip()


def _salvage_function_calls(message: AIMessage) -> AIMessage:
    """Promote raw <function=NAME> blocks in AIMessage.content to real tool_calls.

    Returns the message unchanged when no legacy blocks are present.
    """
    content = message.content
    if not isinstance(content, str) or "<function=" not in content:
        return message

    calls = []
    for m in _FUNCTION_BLOCK_RE.finditer(content):
        name = m.group(1)
        body = m.group(2) or ""
        args: Dict[str, Any] = {}
        for pm in _PARAMETER_RE.finditer(body):
            raw_val = (pm.group(2) or "").strip()
            try:
                args[pm.group(1)] = _json.loads(raw_val)
            except (ValueError, TypeError):
                args[pm.group(1)] = raw_val
        calls.append(
            {
                "name": name,
                "args": args,
                "id": f"call-salvaged-{uuid.uuid4().hex[:12]}",
                "type": "tool_call",
            }
        )
    if not calls:
        return message

    cleaned = _strip_function_syntax(content)
    logger.info(
        "Salvaged %d raw <function=...> block(s) from message content into tool_calls",
        len(calls),
    )
    return message.model_copy(
        update={"tool_calls": calls, "content": cleaned}
    )


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


def _build_existing_chat_model(prefer_fallback: bool = False):
    """Create the chat model via the ORIGINAL OpenAI-compatible path.

    prefer_fallback=False → the primary provider from settings.
    prefer_fallback=True  → the fallback provider (z.ai internal API or
                            FALLBACK_* env config); returns None when no
                            fallback is configured.

    Kept verbatim behind the provider seam (``AGENT_PROVIDER=existing``,
    the default) so the existing behaviour is preserved byte-for-byte.
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


def _build_chat_model(prefer_fallback: bool = False):
    """Create the chat model through the configured AGENT_PROVIDER adapter.

    The provider abstraction keeps the existing runtime (flows, agents,
    tools, events) untouched — only the model layer is swapped:
    - ``existing`` (default) → the original OpenAI-compatible path above
      (in this deployment: the NVIDIA NIM gateway from API_BASE/MODEL_NAME).
    Falls back to the existing path when the selected provider is not
    usable so chat can never break.
    """
    from app.domain.services.agents.provider_factory import get_agent_provider

    provider = get_agent_provider()
    model = provider.build_chat_model(prefer_fallback=prefer_fallback)
    if model is not None:
        return model
    if prefer_fallback:
        return None  # no fallback configured — original contract preserved
    logger.warning(
        "Provider %r returned no model — falling back to 'existing' path",
        provider.name,
    )
    from app.domain.services.agents.providers import OpenAICompatProvider

    return OpenAICompatProvider().build_chat_model(prefer_fallback=False)


def _provider_history(messages) -> list:
    """Project stored LangChain history into the provider's protocol shape
    (no-op for the default OpenAI-compatible path)."""
    from app.domain.services.agents.history_adapter import (
        convert_history_for_provider,
    )
    from app.domain.services.agents.provider_factory import get_agent_provider

    return convert_history_for_provider(get_agent_provider().name, messages)


def _provider_bind_kwargs(response_format, tool_choice) -> dict:
    """Bind kwargs filtered by the provider's capability contract.

    ``response_format`` is an OpenAI-only concept — any future adapter that
    does not support it (``supports_response_format=False``) must never
    receive it or the SDK rejects the request. ``tool_choice`` is
    provider-portable. The default provider (NVIDIA gateway) supports it.
    """
    from app.domain.services.agents.provider_factory import get_agent_provider

    provider = get_agent_provider()
    kwargs: dict = {}
    if response_format is not None and provider.supports_response_format:
        kwargs["response_format"] = response_format
    if tool_choice:
        kwargs["tool_choice"] = tool_choice
    return kwargs


logger = logging.getLogger(__name__)
class BaseAgent(ABC):
    """
    Base agent class, defining the basic behavior of the agent
    """

    name: str = ""
    system_prompt: str = ""
    format: Optional[str] = None
    # Tool-loop rounds per step. 0 = UNLIMITED (default): the loop ends
    # when the model stops calling tools (goal met), not when a counter
    # runs out — big builds legitimately need many rounds. Positive
    # values cap the loop (tests, cost caps).
    max_iterations: int = 0
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
        # Manus registry gate (v1.1) — created lazily, persists per task run
        # so loop-safety streaks, trace, and confirmation approvals survive
        # across plan steps within the same task.
        self._manus_gate: Optional[Any] = None
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

    # ── Manus registry gate helpers (v1.1 standard) ─────────────────────
    def _manus_gate_instance(self) -> Optional[Any]:
        """Lazily build the per-agent ManusGate (None when disabled/broken)."""
        if getattr(self, "_manus_gate", None) is not None:
            return self._manus_gate
        try:
            settings = get_settings()
            if not settings.manus_registry_enabled:
                return None
            from app.domain.services.manus_registry.gate import ManusGate
            self._manus_gate = ManusGate(self)
            return self._manus_gate
        except Exception:
            logger.exception("ManusGate initialization failed — legacy path active")
            return None

    async def _manus_process_call(
        self,
        function_name: str,
        tool_call_id: str,
        function_args: Dict[str, Any],
        brief: str,
    ) -> Optional[ToolMessage]:
        """Run the registry gate for one tool call.

        Returns a ToolMessage when the registry governs this tool (executed
        via MCP/Shell transport, or rejected with a structured error the
        model can repair). Returns None for platform-native tools so the
        legacy toolkit dispatch runs unchanged.
        """
        gate = self._manus_gate_instance()
        if gate is None:
            return None
        from app.domain.services.manus_registry.loader import get_tool_def
        if get_tool_def(function_name) is None:
            return None
        try:
            return await gate.process(
                tool_name=function_name,
                tool_call_id=tool_call_id,
                arguments=function_args or {},
                brief=brief,
            )
        except Exception as exc:  # noqa: BLE001 — gate failure must not kill the loop
            logger.exception("ManusGate process() failed for %s", function_name)
            import json as _json
            payload = {
                "success": False,
                "tool": function_name,
                "data": None,
                "error": {"code": "EXECUTION_ERROR", "message": str(exc), "details": {}},
                "retryable": False,
            }
            return ToolMessage(
                tool_call_id=tool_call_id,
                name=function_name,
                content=_json.dumps(payload, ensure_ascii=False),
                artifact=ToolResult(success=False, message=str(exc)),
            )

    def _tools_with_brief(self) -> List[Any]:
        """OpenAI tool schemas shown to the model.

        Manus registry mode (default): the 31 MCP + 16 shell tools load
        DYNAMICALLY from registry.json — their schemas are the registry's
        input_schema, never a Python decorator. Platform-native tools not
        governed by the registry keep their Python schemas (with the
        required ``brief`` parameter injected). Registry names win over
        Python duplicates, so the surface can never double-define a name.
        """
        try:
            settings = get_settings()
            if settings.manus_registry_enabled:
                from app.domain.services.manus_registry.gate import registry_llm_schemas
                return registry_llm_schemas(self)
        except Exception:
            logger.exception("registry schema build failed — legacy schemas active")
        # ── Legacy path (MANUS_REGISTRY_ENABLED=false) ──
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

        # Error bodies (HTTP pages, tracebacks) can be huge too — cap them
        # so one failure can't poison the context for every later round.
        try:
            _limit = int(getattr(get_settings(), "tool_result_max_chars", 48_000) or 0)
        except Exception:
            _limit = 48_000
        # Attach a failed ToolResult artifact so the ToolEvent carries the
        # real error message — without it the event's function_result is
        # null and the UI renders the tool as "(No Content)" instead of
        # showing what actually went wrong.
        error_result = ToolResult(success=False, message=last_error)
        return ToolMessage(
            tool_call_id=tool_call["id"], name=tool.name,
            content=cap_tool_content(error_result.model_dump_json(), _limit),
            artifact=error_result,
        )
    
    # Compact browser tool results in memory every this many tool-call rounds
    # within a single step to prevent "Payload Too Large" on complex pages.
    _COMPACT_EVERY_N_ITERATIONS = 10

    # ── Context-overflow defense (provider error 1261) ───────────────────
    # Provider prompt-limit errors observed in the wild:
    #   HTTP 400 {'error': {'code': '1261', 'message': 'Prompt exceeds max length'}}
    #   "This model's maximum context length is X tokens..."
    #   "prompt is too long", "input is too long", "too many input tokens"
    # Retrying unchanged is pointless — the conversation itself must
    # shrink first. Two mechanisms cooperate:
    #   1. PROACTIVE: before every LLM call, estimate the serialized
    #      conversation size; above context_soft_limit_chars compact
    #      progressively (browser-use-style prevention).
    #   2. REACTIVE: when the provider STILL rejects the prompt, run the
    #      emergency ladder (aggressive compact → drop old rounds),
    #      re-snapshot the context and retry — instead of killing the
    #      task after all the work is done (the final summary used to
    #      die exactly this way on image-heavy tasks).
    _MAX_CONTEXT_OVERFLOW_RECOVERIES = 2

    _CONTEXT_OVERFLOW_MARKERS = (
        "exceeds max length",
        "prompt is too long",
        "prompt too long",
        "prompt exceeds",
        "context length",
        "context window",
        "maximum context",
        "max tokens exceeded",
        "too many tokens",
        "too many input tokens",
        "input is too long",
        "input too long",
        "reduce the length",
        "reduce your prompt",
        "request is too large",
    )

    @staticmethod
    def _is_context_overflow_error(exc: Exception) -> bool:
        """Whether a provider error means the PROMPT is too large for the
        model's context window (as opposed to key/quota limits — see
        ``_is_limit_error``). Used to trigger emergency compaction."""
        text = str(exc).lower()
        if any(marker in text for marker in BaseAgent._CONTEXT_OVERFLOW_MARKERS):
            return True
        # NVIDIA's integrate API uses a numeric code: '1261'.
        if "1261" in text and isinstance(exc, (openai.APIStatusError, ValueError)):
            return True
        status = getattr(exc, "status_code", None)
        if status == 400 and any(
            word in text for word in ("length", "token", "prompt", "input")
        ):
            return True
        return False

    @staticmethod
    def _estimate_context_chars(messages) -> int:
        """Cheap character-count estimate of the serialized conversation.

        Counts message contents (text + multimodal parts — a base64
        image_url part is a huge string, so it is included) plus the
        serialized tool_call arguments. ~4 chars/token for English;
        deliberately conservative (over-estimates) so compaction fires
        early rather than late.
        """
        total = 0
        for message in messages:
            content = getattr(message, "content", None)
            if isinstance(content, str):
                total += len(content)
            elif isinstance(content, list):
                for part in content:
                    if isinstance(part, dict):
                        text = part.get("text")
                        if isinstance(text, str):
                            total += len(text)
                        else:
                            total += len(str(part))
                    else:
                        total += len(str(part))
            elif content is not None:
                total += len(str(content))
            for tool_call in (getattr(message, "tool_calls", None) or []):
                try:
                    total += len(_json.dumps(tool_call.get("args", {}), default=str))
                except Exception:
                    total += len(str(tool_call))
        return total

    def _context_soft_limit(self) -> int:
        try:
            return int(
                getattr(get_settings(), "context_soft_limit_chars", 280_000) or 0
            )
        except Exception:
            return 280_000

    async def _enforce_context_budget(self) -> None:
        """Proactive gate: shrink memory BEFORE the prompt can blow the
        provider's limit (browser-use's ``maybe_compact_messages`` idea,
        but deterministic — no summarisation LLM call on the hot path).

        Ladder: estimate → map-reduce compact (LLM-distilled summary of the
        about-to-be-lost context, falling back to plain truncation) →
        aggressive compact → drop old rounds. Every rung is in-place and
        persisted; the agent can always re-read files / re-run commands if
        it truly needs dropped detail back.
        """
        limit = self._context_soft_limit()
        if limit <= 0:
            return
        await self._ensure_memory()
        if self._estimate_context_chars(self.memory.get_messages()) <= limit:
            return

        before_msgs = len(self.memory.messages)
        before_chars = self._estimate_context_chars(self.memory.get_messages())
        # Map-reduce first (natural distillation); its internals degrade to
        # the plain compact when the summarizer is unavailable/fails.
        try:
            summarized = await self.memory.compact_with_summary(self._summarize_digest)
        except Exception:
            summarized = False
            self.memory.compact()
        # The ladder ALWAYS continues: a distilled summary preserves the
        # knowledge of dropped content but does NOT guarantee the size fell
        # below the budget — aggressive compaction and round-dropping stay
        # armed exactly like before.
        if self._estimate_context_chars(self.memory.get_messages()) > limit:
            self.memory.compact(aggressive=True)
        if self._estimate_context_chars(self.memory.get_messages()) > limit:
            self.memory.drop_older_rounds()
        after_chars = self._estimate_context_chars(self.memory.get_messages())
        logger.info(
            "Proactive context compaction for agent '%s': %d → %d chars, "
            "%d → %d messages (soft limit %d, distilled=%s)",
            self.name, before_chars, after_chars, before_msgs,
            len(self.memory.messages), limit, summarized,
        )
        try:
            await self._repository.save_memory(self._agent_id, self.name, self.memory)
        except Exception:
            logger.debug("save after proactive compaction failed", exc_info=True)

    async def _summarize_digest(self, digest: str) -> str:
        """LLM map-reduce step: distil a compaction digest into a compact
        rolling summary (facts, decisions, paths, open threads).

        Best-effort by contract: raises on failure so the caller keeps the
        plain-truncation fallback. Uses the agent's current model (primary
        or already-rotated fallback) with a short timeout.
        """
        import asyncio as _asyncio
        from langchain.messages import HumanMessage as _HumanMessage
        from langchain.messages import SystemMessage as _SystemMessage

        prompt = (
            "Distil this completed portion of an agent task into a compact "
            "summary a continuation agent needs: key facts, numbers, "
            "decisions made, file paths touched, errors fixed, and open "
            "threads. At most 200 words. Plain text, no preamble.\n\n"
            f"{digest}"
        )
        response = await _asyncio.wait_for(
            self._model.ainvoke(
                [
                    _SystemMessage(content="You are a precise summariser."),
                    _HumanMessage(content=prompt),
                ]
            ),
            timeout=30.0,
        )
        content = response.content if hasattr(response, "content") else ""
        if isinstance(content, list):
            content = "".join(
                b.get("text", "") for b in content if isinstance(b, dict)
            )
        return (content or "").strip()

    async def _emergency_context_reduction(self, escalate: bool) -> None:
        """In-flight recovery after the provider rejected an oversized
        prompt (error 1261 family). Decisive by design — the request has
        already failed once, so always aggressive-compact, and on the
        second failure also drop whole old rounds (and harder)."""
        await self._ensure_memory()
        before_chars = self._estimate_context_chars(self.memory.get_messages())
        self.memory.compact(aggressive=True)
        if escalate:
            self.memory.drop_older_rounds()
            limit = self._context_soft_limit()
            if limit > 0 and self._estimate_context_chars(
                self.memory.get_messages()
            ) > limit:
                self.memory.drop_older_rounds(keep_last_messages=4)
        after_chars = self._estimate_context_chars(self.memory.get_messages())
        logger.warning(
            "EMERGENCY context compaction for agent '%s' (escalate=%s): "
            "%d → %d chars",
            self.name, escalate, before_chars, after_chars,
        )
        try:
            await self._repository.save_memory(self._agent_id, self.name, self.memory)
        except Exception:
            logger.debug("save after emergency compaction failed", exc_info=True)

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

    def _goal_reminder(self) -> Optional[str]:
        """Goal text for the periodic GOAL CHECK advisory; None disables it.

        Base agents have no step notion — the ExecutionAgent overrides
        this to return the current step description (see execution.py),
        which keeps long tool loops aimed at the step's objective.
        """
        return None

    async def execute(self, request: Union[str, list], format: Optional[str] = None) -> AsyncGenerator[BaseEvent, None]:
        format = format or self.format

        # ── Agent orchestrator contract v1.0: run bootstrap ─────────────
        # agent_started event (notification-event-bus) + in-band approval
        # hook: the user's reply may BE the confirmation answer ("ya") for
        # a pending consequential action, so the ledger must see it BEFORE
        # the first tool call of this run (contract: "resume same task
        # after approval" — this wiring was previously missing entirely).
        try:
            _ctx = getattr(self, "task_context", None)
            if _ctx and get_settings().manus_registry_enabled:
                from app.domain.services.manus_registry.notify import ensure_run_started
                ensure_run_started(
                    str(_ctx.get("session_id") or "unknown"),
                    str(_ctx.get("task_id")),
                    _ctx.get("user_id"),
                    user_message=request if isinstance(request, str) else "",
                )
                if isinstance(request, str) and request.strip():
                    _boot_gate = self._manus_gate_instance()
                    if _boot_gate is not None:
                        _boot_gate.confirmations.register_user_reply(request)
        except Exception:  # noqa: BLE001 — contract glue must never break the loop
            logger.debug("agent run bootstrap failed", exc_info=True)

        message = await self.ask(request, format)

        # ── Adaptive-loop instrumentation (ported from browser-use) ──────
        # The flat tool loop below lets a model burn its entire iteration
        # budget retrying one failing action (observed live: 25 identical
        # el.click() retries on a React dropdown until "Maximum iteration
        # count reached"). browser-use solves this with soft signals fed
        # back into the conversation; we port the same three:
        #   1. action repetition / stagnation nudges (ActionLoopDetector)
        #   2. consecutive-failure budget annotated on failed results
        #   3. step-budget warnings (>=75% used / last rounds)
        from app.domain.services.agents.loop_detector import ActionLoopDetector

        loop_detector = ActionLoopDetector()
        # ── Hard loop guard (Codex/Claude-Code-style harness discipline) ──
        # The soft nudges above ask the model to self-correct; weak models
        # ignore them (observed live: `npx tailwindcss init -p` failed 4x
        # with interleaved `ls` probes resetting the old consecutive-only
        # counter — ~25 minutes burned on one dead approach). The HARD
        # guard denies execution of known non-progress calls: blind
        # repeats (same call + same outcome + nothing changed in between)
        # and command families that keep failing without any state change.
        # Blocked calls return a diagnostic payload with the last error
        # excerpt + pivot checklist, so the model is FORCED to read the
        # error and change method — exactly how a coding-agent harness
        # keeps the loop productive. Applies to BOTH dispatch paths
        # (registry gate and legacy toolkits) via the shared window below.
        from app.domain.services.manus_registry.trace import (
            LoopSafety,
            arguments_hash as _guard_args_hash,
        )

        hard_guard = LoopSafety()
        _consecutive_failed_rounds = 0
        _settings = get_settings()
        # Display-only budget for the failure annotations (browser-use uses
        # settings.max_failures the same way). Hard stops stay upstream in
        # the plan-act flow, which already tracks step-level failures.
        _failure_budget = max(1, int(_settings.max_consecutive_failures))

        # 0 (or None) = UNLIMITED tool rounds: iterate forever until the
        # model stops emitting tool_calls. Finite values keep the classic
        # cap + budget advisories. Implemented via itertools.count() so the
        # for-else "Maximum iteration count reached" branch stays reachable
        # ONLY on the finite path.
        _finite_iterations = isinstance(self.max_iterations, int) and self.max_iterations > 0
        _iterations = (
            range(self.max_iterations) if _finite_iterations else itertools.count()
        )
        for iteration in _iterations:
            # Legacy wire-format leak repair: models sometimes emit raw
            # <function=...> blocks as plain content instead of tool_calls.
            message = _salvage_function_calls(message)
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
            _round_had_success = False
            _round_had_failure = False
            tool_responses = []
            for tool_call in message.tool_calls:
                function_name = tool_call["name"]
                tool_call_id = tool_call["id"] = tool_call["id"] or str(uuid.uuid4())
                function_args = tool_call["args"]

                # ── Hard loop guard (pre-dispatch, BOTH paths) ─────────
                # Known non-progress calls never reach an executor: they
                # get a diagnostic LOOP_DETECTED payload with the last
                # error excerpt + pivot checklist instead.
                _guard_args = dict(function_args or {})
                try:
                    _guard_hash = _guard_args_hash(function_name, _guard_args)
                    _guard_block = hard_guard.check_before_execute(
                        function_name, _guard_hash, _guard_args
                    )
                except Exception:  # noqa: BLE001 — guard must never break dispatch
                    logger.debug("hard guard check failed", exc_info=True)
                    _guard_hash = ""
                    _guard_block = None
                if _guard_block is not None:
                    _guard_err = (_guard_block.get("error") or {}).get("message", "")
                    _guard_artifact = ToolResult(
                        success=False,
                        message=f"Loop guard: {_guard_err}",
                    )
                    yield ToolEvent(
                        status=ToolStatus.CALLING,
                        tool_call_id=tool_call_id,
                        tool_name=function_name.split("_", 1)[0],
                        function_name=function_name,
                        function_args=_guard_args,
                    )
                    _round_had_failure = True
                    yield MessageEvent(
                        message=(
                            "Terdeteksi aksi berulang yang gagal terus — "
                            "guard memblokirnya dan memaksa strategi baru."
                        ),
                        is_progress=True,
                        role="assistant",
                    )
                    yield ToolEvent(
                        status=ToolStatus.CALLED,
                        tool_call_id=tool_call_id,
                        tool_name=function_name.split("_", 1)[0],
                        function_name=function_name,
                        function_args=_guard_args,
                        function_result=_guard_artifact,
                    )
                    tool_responses.append(ToolMessage(
                        tool_call_id=tool_call_id,
                        name=function_name,
                        content=json.dumps(_guard_block, ensure_ascii=False),
                        artifact=_guard_artifact,
                    ))
                    loop_detector.record_action(function_name, _guard_args)
                    loop_detector.record_result(
                        function_name, json.dumps(_guard_block)
                    )
                    logger.warning(
                        "Hard loop guard BLOCKED %s: %s",
                        function_name, _guard_err[:160],
                    )
                    continue

                # ── Manus registry gate (v1.1) ──────────────────────────
                # Registry-governed tools (31 MCP + 16 shell) are validated
                # and executed HERE — before legacy toolkit resolution —
                # because most of them have no Python Tool instance. The
                # gate returns a normalized ToolMessage (tool_call_id
                # preserved) or None for platform-native tools.
                try:
                    _gate_brief, _gate_args = _take_brief(dict(function_args or {}))
                    from app.domain.services.agents.opencode_adapter import (
                        is_read_only_mode,
                        is_read_only_tool,
                        readonly_tool_message,
                    )
                    if is_read_only_mode() and not is_read_only_tool(function_name):
                        _gate_message = readonly_tool_message(
                            function_name, tool_call_id
                        )
                    else:
                        _gate_message = await self._manus_process_call(
                            function_name, tool_call_id, _gate_args, _gate_brief or ""
                        )
                except Exception:  # noqa: BLE001 — never break the loop from the gate
                    logger.exception("gate dispatch crashed for %s", function_name)
                    _gate_message = None
                if _gate_message is not None:
                    _event_toolkit = function_name.split("_", 1)[0] \
                        if function_name.startswith(("browser_", "webdev_")) \
                        else ("image" if function_name.startswith("generate_") else "mcp")
                    if function_name.startswith("manus-"):
                        _event_toolkit = "shell"
                    yield ToolEvent(
                        status=ToolStatus.CALLING,
                        tool_call_id=tool_call_id,
                        tool_name=_event_toolkit,
                        function_name=function_name,
                        function_args=_gate_args,
                        brief=_gate_brief or "",
                    )
                    _gate_artifact = getattr(_gate_message, "artifact", None)
                    _gate_failed = _gate_artifact is None or (
                        hasattr(_gate_artifact, "success")
                        and _gate_artifact.success is False
                    )
                    if _gate_failed:
                        _round_had_failure = True
                        # Mirror the legacy failure-budget annotation so the
                        # loop-awareness contract holds on BOTH paths.
                        if _consecutive_failed_rounds >= 1:
                            _note = (
                                f"[SYSTEM NOTE: this action failed. Failed action "
                                f"rounds so far: {_consecutive_failed_rounds}/"
                                f"{_failure_budget}. Repeating identical arguments "
                                f"will not help - change strategy or pick a "
                                f"different tool.]"
                            )
                            try:
                                import json as _json
                                _body = _json.loads(_gate_message.content)
                                _body["system_note"] = _note
                                _gate_message.content = _json.dumps(
                                    _body, ensure_ascii=False
                                )
                            except Exception:  # noqa: BLE001
                                _gate_message.content = (
                                    f"{_gate_message.content}\n\n{_note}"
                                )
                    else:
                        _round_had_success = True
                    loop_detector.record_action(function_name, _gate_args)
                    loop_detector.record_result(function_name, _gate_message.content)
                    # Hard-guard outcome memory (gate path) — same window
                    # as the legacy path so dispatch route is irrelevant.
                    try:
                        _gp = json.loads(_gate_message.content)
                        _g_ok = bool(_gp.get("success"))
                        _g_err = _gp.get("error") or {}
                        _g_excerpt = ""
                        if _g_ok:
                            _g_excerpt = json.dumps(
                                _gp.get("data"), ensure_ascii=False, default=str
                            )[:300]
                        hard_guard.record_result(
                            function_name, _guard_hash, _g_ok,
                            error_code=str(_g_err.get("code", "")),
                            error_message=str(_g_err.get("message", ""))[:300],
                            output_excerpt=_g_excerpt,
                            arguments=_gate_args,
                        )
                    except Exception:  # noqa: BLE001
                        logger.debug("hard guard gate-path record failed", exc_info=True)
                    yield ToolEvent(
                        status=ToolStatus.CALLED,
                        tool_call_id=tool_call_id,
                        tool_name=_event_toolkit,
                        function_name=function_name,
                        function_args=_gate_args,
                        function_result=_gate_artifact,
                        brief=_gate_brief or "",
                    )
                    tool_responses.append(_gate_message)
                    continue

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

                # ── Command-level honesty (transport ≠ command success) ──
                # The sandbox transport reports success=True as long as the
                # shell session executed; the COMMAND inside may have exited
                # non-zero ("npm error could not determine executable to
                # run", rc=1). Observed live on session deeadb25: the model
                # read success:true and every downstream guard (failure
                # budget, loop guard, ghost-success detection) saw "ok" for
                # a dead command. Codex/Claude-Code rule: a non-zero exit
                # IS a failure — surface it to the model, the UI, and the
                # guards alike.
                _artifact = getattr(tool_result, "artifact", None)
                if function_name.startswith("shell_") and isinstance(
                    getattr(_artifact, "data", None), dict
                ):
                    try:
                        _rc = int(_artifact.data.get("returncode"))
                    except (TypeError, ValueError):
                        _rc = None
                    if _rc is not None and _rc != 0 and getattr(_artifact, "success", True):
                        _out = str(
                            _artifact.data.get("output")
                            or _artifact.data.get("stderr")
                            or ""
                        )
                        _fail_note = (
                            f"Command failed with exit code {_rc}. "
                            + (_out[:200] if _out else "")
                        ).strip()
                        try:
                            _artifact.success = False
                            _artifact.message = _fail_note
                            _tr_obj = json.loads(tool_result.content)
                            _tr_obj["success"] = False
                            _tr_obj["message"] = _fail_note
                            tool_result.content = json.dumps(
                                _tr_obj, ensure_ascii=False
                            )
                        except Exception:  # noqa: BLE001 — honesty best-effort
                            logger.debug("exit-code honesty rewrite failed", exc_info=True)

                # ── Adaptive-loop bookkeeping ──────────────────────────
                # A call "failed" when its ToolResult carries success=False
                # or when invoke_tool returned an exception payload (no
                # artifact). Feeds the failure budget + loop detector.
                _artifact = getattr(tool_result, "artifact", None)
                _call_failed = _artifact is None or (
                    hasattr(_artifact, "success") and _artifact.success is False
                )
                # Signature captured BEFORE any annotation is appended below,
                # so byte-identical failing results still hash identically
                # (stagnation detection depends on this).
                _content_signature = tool_result.content
                if _call_failed:
                    _round_had_failure = True
                    if _consecutive_failed_rounds >= 1:
                        # browser-use style budget on the feedback itself so
                        # the model knows how deep it is in a failure streak.
                        tool_result.content = (
                            f"{tool_result.content}\n\n"
                            f"[SYSTEM NOTE: this action failed. Failed action "
                            f"rounds so far: {_consecutive_failed_rounds}/"
                            f"{_failure_budget}. Repeating identical arguments "
                            f"will not help - change strategy or pick a "
                            f"different tool.]"
                        )
                else:
                    _round_had_success = True
                loop_detector.record_action(function_name, function_args)
                loop_detector.record_result(function_name, _content_signature)
                # Hard-guard outcome memory (legacy path).
                try:
                    _hg_excerpt = ""
                    if _artifact is not None and getattr(_artifact, "data", None) is not None:
                        _hg_excerpt = json.dumps(
                            _artifact.data, ensure_ascii=False, default=str
                        )[:300]
                    _hg_stop = hard_guard.record_result(
                        function_name, _guard_hash, not _call_failed,
                        error_code=("EXECUTION_ERROR" if _call_failed else ""),
                        error_message=(
                            str(getattr(_artifact, "message", "") or "")[:300]
                            if _call_failed else ""
                        ),
                        output_excerpt=_hg_excerpt,
                        arguments=function_args,
                    )
                    if _hg_stop is not None:
                        # Same call keeps failing with the same error: turn
                        # THIS result into the structured stop payload so the
                        # model reads the diagnosis, not a stale error again.
                        _hg_artifact = ToolResult(
                            success=False,
                            message=(
                                "Loop guard: "
                                + str((_hg_stop.get("error") or {}).get("message", ""))
                            ),
                        )
                        tool_result.content = json.dumps(
                            _hg_stop, ensure_ascii=False
                        )
                        tool_result.artifact = _hg_artifact
                except Exception:  # noqa: BLE001
                    logger.debug("hard guard legacy-path record failed", exc_info=True)

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

            # Round-level failure accounting (browser-use counts failed
            # single-action steps; any success resets the streak).
            if _round_had_failure and not _round_had_success:
                _consecutive_failed_rounds += 1
            elif _round_had_success:
                _consecutive_failed_rounds = 0

            # Periodically compact browser tool results mid-step to prevent
            # "Payload Too Large" errors on pages with hundreds of elements.
            if (iteration + 1) % self._COMPACT_EVERY_N_ITERATIONS == 0:
                logger.debug(f"Mid-step compact at iteration {iteration + 1}")
                await self.compact_memory()

            # ── Adaptive-loop context injections (browser-use nudges) ──
            # Soft advisories appended AFTER the ToolMessages (valid message
            # ordering for OpenAI/Anthropic) so the model sees them on its
            # very next decision — this is what makes the loop "aware".
            _advisories: List[str] = []
            _nudge = loop_detector.get_nudge_message()
            if _nudge:
                _advisories.append(_nudge)
                if loop_detector.max_repetition_count >= 6:
                    # Let the user see the self-correction happening live.
                    yield MessageEvent(
                        message=(
                            f"Detected a repeated-action loop "
                            f"({loop_detector.max_repetition_count}x) - "
                            f"switching strategy."
                        ),
                        is_progress=True,
                        role="assistant",
                    )

            # ── Goal-directedness: periodic GOAL CHECK re-anchoring ────
            # Long tool loops drift: the model starts re-exploring the same
            # ground (the "muter-muter" the user watches live) instead of
            # advancing the step. Every 3 rounds from round 3, re-inject the
            # CURRENT step goal so every next action is chosen against the
            # objective, not against the previous tool result.
            _rounds_used = iteration + 1
            _goal_text = self._goal_reminder()
            if (
                _goal_text
                and _rounds_used >= 3
                and _rounds_used % 3 == 0
            ):
                _advisories.append(
                    f"GOAL CHECK: the current step's goal is: "
                    f"{_goal_text[:400]}. Before choosing your next action, "
                    "confirm it DIRECTLY advances this goal. If the goal is "
                    "already achieved, stop calling tools and emit your "
                    "final result now. If you are re-visiting ground you "
                    "already covered without new information, consolidate "
                    "what you have and conclude the step honestly."
                )

            # Step-budget awareness (browser-use _inject_budget_warning).
            if (
                self.max_iterations > 0
                and _rounds_used < self.max_iterations
                and _rounds_used / self.max_iterations >= 0.75
            ):
                _remaining = self.max_iterations - _rounds_used
                _advisories.append(
                    f"BUDGET WARNING: you have used {_rounds_used}/"
                    f"{self.max_iterations} action rounds "
                    f"({int(_rounds_used / self.max_iterations * 100)}%). "
                    f"{_remaining} rounds remain. If the step cannot be "
                    f"fully completed in the remaining budget, prioritise "
                    f"consolidating what you already have and finish with an "
                    f"honest partial result - partial results are far more "
                    f"valuable than exhausting the budget with retries."
                )

            # Last-rounds wrap-up (browser-use _force_done_after_last_step,
            # adapted: we ask for the final result JSON instead of a done()
            # tool call, matching this executor's output contract).
            # Finite path only — an unlimited loop has no "last rounds".
            if _finite_iterations and iteration >= self.max_iterations - 2:
                _advisories.append(
                    "LAST ROUNDS: you are at the end of this step's action "
                    "budget. Do NOT start anything new. Unless one final "
                    "action completes the step, stop calling tools and emit "
                    "your final result now, summarising what was accomplished "
                    "and what remains incomplete."
                )

            # Strategy-change advisory on failure streaks (browser-use's
            # replan nudge, in-loop because our replanning lives one level
            # up in the plan-act flow).
            if _consecutive_failed_rounds >= _failure_budget:
                _advisories.append(
                    f"STRATEGY CHANGE REQUIRED: {_consecutive_failed_rounds} "
                    "consecutive action rounds have failed. The current "
                    "approach is not working. Choose a fundamentally "
                    "different method (different tool, different element, "
                    "JavaScript or shell fallback) - or conclude the step "
                    "honestly with the data collected so far."
                )

            if _advisories:
                tool_responses.append(HumanMessage(content="\n\n".join(_advisories)))
                logger.info(
                    "Adaptive-loop advisory injected (round %s): %s",
                    f"{_rounds_used}/{self.max_iterations}" if _finite_iterations else f"{_rounds_used}/unlimited",
                    " | ".join(a.splitlines()[0][:80] for a in _advisories),
                )

            # ── Optional subclass hook: end-of-round observer ─────────────
            # Lets a subclass watch the tool loop and inject events between
            # rounds (e.g. live plan progress during long-running steps)
            # without overriding the whole loop.  Absent by default.
            _round_hook = getattr(self, "_on_tool_round_end", None)
            if _round_hook is not None:
                async for hook_event in _round_hook(iteration):
                    yield hook_event

            message = await self.ask_with_messages(tool_responses)
        else:
            yield ErrorEvent(error="Maximum iteration count reached, failed to complete the task")
        
        yield MessageEvent(message=_strip_function_syntax(message.content))
    
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

        # Proactive context gate: if the accumulated memory has grown past
        # the soft budget, compact BEFORE sending anything — cheaper than
        # burning a round-trip on a guaranteed 400.
        await self._enforce_context_budget()

        response_format = None
        if format:
            response_format = {"type": format}

        # Stage 1-3: model chain | RobustJsonParser repairs invalid tool call JSON.
        # Stages 4-5: outer retry loop handles cases that survive stages 1-3.
        def _build_chain():
            return (
                self._model
                .bind(**_provider_bind_kwargs(response_format, self.tool_choice))
                .bind_tools(self._tools_with_brief())
                | RobustJsonParser.from_llm(self._model)
            )

        chain = _build_chain()

        # Provider-neutral error vocabulary (providers.ProviderErrorKind).
        # Adapters return exceptions classified into the SAME kinds the
        # ladder below handles (auth → fallback swap, transient → back-off,
        # rate limit → patient rotation, status → compaction/rotation) —
        # semantics stay identical no matter which adapter is active. The
        # "No endpoints found" pool recycling quirk is OpenRouter-specific.
        from app.domain.services.agents.provider_factory import get_agent_provider

        _turn_provider = get_agent_provider()
        _TRANSIENT_API_ERRORS = _turn_provider.transient_error_types()
        _AUTH_API_ERRORS = _turn_provider.auth_error_types()
        _STATUS_API_ERRORS = _turn_provider.status_error_types()

        context = _provider_history(self.memory.get_messages())
        attempt = 0
        _overflow_recoveries = 0
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
            except _AUTH_API_ERRORS as e:
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
                if self._is_context_overflow_error(e):
                    # Prompt-limit failures (1261 family) — shrink the
                    # conversation, re-snapshot and retry (see the
                    # APIStatusError branch for the full ladder).
                    if _overflow_recoveries >= self._MAX_CONTEXT_OVERFLOW_RECOVERIES:
                        logger.error(
                            "Prompt still exceeds the model context limit "
                            "after %d emergency compactions, giving up",
                            _overflow_recoveries,
                        )
                        raise
                    _overflow_recoveries += 1
                    await self._emergency_context_reduction(
                        escalate=_overflow_recoveries > 1
                    )
                    context = _provider_history(self.memory.get_messages())
                    continue
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
            except _STATUS_API_ERRORS as e:
                # Prompt-limit errors (NVIDIA 400/1261 "Prompt exceeds max
                # length", OpenAI "maximum context length", Anthropic
                # "prompt is too long") used to fall through every clause
                # and kill the whole task mid-run — after all the work was
                # already done. Emergency ladder instead:
                #   recovery 1 — aggressive compaction, retry
                #   recovery 2 — + drop oldest rounds (protocol-safe), retry
                #   then give up with the original error.
                if self._is_context_overflow_error(e):
                    if _overflow_recoveries >= self._MAX_CONTEXT_OVERFLOW_RECOVERIES:
                        logger.error(
                            "Prompt still exceeds the model context limit "
                            "after %d emergency compactions, giving up: %s",
                            _overflow_recoveries, e,
                        )
                        raise
                    _overflow_recoveries += 1
                    await self._emergency_context_reduction(
                        escalate=_overflow_recoveries > 1
                    )
                    # Re-snapshot: compaction mutates/removes messages in
                    # memory; the local `context` list must reflect that.
                    context = _provider_history(self.memory.get_messages())
                    logger.warning(
                        "Context overflow (attempt %d/%d) — compacted, "
                        "retrying with %d messages",
                        _overflow_recoveries,
                        self._MAX_CONTEXT_OVERFLOW_RECOVERIES,
                        len(context),
                    )
                    continue
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

    async def astream_chunks_with_fallback(self, messages) -> AsyncGenerator[str, None]:
        """Yield text chunks from a direct model stream with provider fallback.

        Direct streams are used for short user-facing responses such as the
        initial acknowledgement and the final summary.  A provider normally
        rejects a request before sending its first chunk, so retries are safe
        while ``emitted`` is false.  Once a provider has sent content, retrying
        would duplicate text in the UI; surface that error instead.

        Context overflow (error 1261 family): the FINAL SUMMARY streams the
        agent's ENTIRE accumulated memory — on long research/build tasks this
        is exactly where the prompt finally exceeded the provider limit and
        killed the task after all the work was done.  On such a rejection we
        shrink the message list in place (aggressive compaction + dropping
        the oldest rounds) and retry — the summary only needs the recent
        rounds plus the original task stub to do its job.
        """
        attempt = 0
        _overflow_recoveries = 0
        # Provider-neutral vocabulary for this streaming loop (mirrors the
        # ask_with_messages ladder) + protocol-safe history projection.
        from app.domain.services.agents.provider_factory import get_agent_provider

        _turn_provider = get_agent_provider()
        while True:
            emitted = False
            try:
                async for chunk in self._model.astream(_provider_history(messages)):
                    text = chunk.content if isinstance(chunk.content, str) else ""
                    if text:
                        emitted = True
                        yield text
                return
            except Exception as e:
                if emitted:
                    raise
                if self._is_context_overflow_error(e):
                    if _overflow_recoveries >= self._MAX_CONTEXT_OVERFLOW_RECOVERIES:
                        raise
                    _overflow_recoveries += 1
                    # Mutates the message objects (shared with memory when
                    # the list was built from it) and drops old rounds from
                    # the local list — protocol-safe cut at Human boundaries.
                    compact_messages(messages, aggressive=True)
                    drop_older_rounds(messages)
                    logger.warning(
                        "Context overflow while streaming (recovery %d/%d) — "
                        "compacted to %d messages, retrying",
                        _overflow_recoveries,
                        self._MAX_CONTEXT_OVERFLOW_RECOVERIES,
                        len(messages),
                    )
                    continue
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
                    e, _turn_provider.transient_error_types()
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

    async def astream_text_with_fallback(self, messages) -> str:
        """Collect a direct model stream while preserving fallback behavior."""
        parts: list[str] = []
        async for text in self.astream_chunks_with_fallback(messages):
            parts.append(text)
        return "".join(parts)

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
    
    async def compact_memory(self, aggressive: bool = False) -> None:
        await self._ensure_memory()
        self.memory.compact(aggressive=aggressive)
        await self._repository.save_memory(self._agent_id, self.name, self.memory)
