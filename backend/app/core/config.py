import os
import json
import logging
from pydantic_settings import BaseSettings
from functools import lru_cache

logger = logging.getLogger(__name__)


def _parse_extra_headers() -> dict | None:
    raw = os.environ.get("EXTRA_HEADERS")
    if not raw:
        return None
    try:
        headers = json.loads(raw)
        if isinstance(headers, dict):
            return headers
        logger.warning("EXTRA_HEADERS is not a JSON object, ignoring")
    except json.JSONDecodeError:
        logger.warning("EXTRA_HEADERS is not valid JSON, ignoring")
    return None


class Settings(BaseSettings):
    
    # Model provider configuration
    api_key: str | None = None
    api_base: str | None = None
    
    # Model configuration
    model_name: str = "gpt-4o"
    model_provider: str = "openai"
    temperature: float = 0.7
    max_tokens: int = 2000

    # Fallback model provider — used automatically when the primary provider
    # hits rate limits / quota / auth errors so the agent keeps working.
    # Explicit env config (FALLBACK_*) wins; otherwise the z.ai internal API
    # credentials are auto-discovered from /etc/.z-ai-config when present.
    fallback_api_base: str | None = None
    fallback_api_key: str | None = None
    fallback_model_name: str | None = None
    fallback_token: str | None = None
    fallback_chat_id: str | None = None
    fallback_user_id: str | None = None

    # ── Agent provider abstraction (backward-compatible) ──────────────────
    # Selects WHICH model-provider adapter builds the LLM client used by the
    # existing agent runtime (PlanActFlow / agents / tools / events are all
    # provider-agnostic and stay untouched).
    #   "existing" — the configured OpenAI-compatible gateway (default,
    #                unchanged). In this deployment that gateway is NVIDIA NIM
    #                (API_BASE=https://integrate.api.nvidia.com/v1 +
    #                MODEL_NAME=nvidia/…), i.e. the model already in use.
    # Unknown values safely fall back to "existing". The AgentProvider
    # protocol (agents/providers.py) is the extension point for adding a
    # future adapter — per project decision the Anthropic adapter was removed
    # and the deployment standardizes on the NVIDIA model.
    # env var: AGENT_PROVIDER
    agent_provider: str = "existing"

    # MongoDB configuration
    mongodb_uri: str = "mongodb://localhost:27017"
    mongodb_database: str = "dzeck"
    mongodb_username: str | None = None
    mongodb_password: str | None = None
    
    # Redis configuration
    redis_host: str = "localhost"
    redis_port: int = 6379
    redis_db: int = 0
    redis_password: str | None = None
    
    # Sandbox configuration
    sandbox_address: str | None = None
    sandbox_ttl_minutes: int | None = 30
    # Replit-local sandbox URLs (default to localhost services)
    sandbox_base_url: str = "http://localhost:8080"
    sandbox_vnc_url: str = "ws://localhost:5901"
    sandbox_cdp_url: str = "http://localhost:8222"
    # Virtual display size (Xvfb -screen 0). The browser window is force-fit
    # to exactly this size via CDP on every browser init — there is no window
    # manager in the sandbox, so --start-maximized is silently ignored and the
    # window would otherwise float in the middle of the desktop (making the
    # live VNC view look off-centre vs. the tool screenshots).
    sandbox_display_size: str = "1280x1029"
    # Root directory for per-user sandbox homes. On Replit the runner user owns
    # /home/runner, so the default matches production. Other deployments (where
    # /home/runner cannot be created) can override it via USER_HOME_ROOT.
    user_home_root: str = "/home/runner/users"

    # App source directory the sandbox agent must NEVER touch (prompt-level
    # prohibition; hard enforcement lives in the sandbox service's
    # PROTECTED_PATHS). Colon/comma separated. Defaults to the Replit layout;
    # other deployments point it at their own app source tree.
    sandbox_protected_paths: str = "/home/runner/workspace"

    # ── Sandbox provider selection ─────────────────────────────────────────
    # "auto"    → prefer E2B (per-user isolated cloud sandbox), fall back to
    #             the shared Replit-local sandbox on any E2B failure/quota.
    # "e2b"     → same as auto (fallback always keeps the app alive).
    # "replit"  → always use the shared local sandbox (E2B disabled).
    sandbox_provider: str = "auto"
    # E2B API key (https://e2b.dev). When None, E2B is skipped entirely.
    e2b_api_key: str | None = None
    # Seconds before an idle E2B sandbox is paused (paused sandboxes keep
    # their filesystem and are resumed automatically on the next turn).
    e2b_sandbox_timeout: int = 3600

    # Vision model configuration (optional, for browser screenshot analysis)
    vision_model_name: str | None = None
    vision_model_provider: str | None = None
    vision_api_base: str | None = None
    vision_api_key: str | None = None

    # Summary model configuration (optional, for session title generation)
    summary_model_name: str | None = None

    # Browser engine configuration
    browser_engine: str = "browser_use"  # "playwright" or "browser_use"
    
    # Search engine configuration
    search_provider: str | None = "bing_web"  # "baidu", "baidu_web", "google", "bing", "bing_web", "bing_rss", "tavily"
    # Automatic fallback provider used when the primary is unreachable (e.g.
    # Tavily's WAF blocks datacenter IPs). Applied to the "tavily" provider.
    # "bing_rss" merges Bing web+news RSS endpoints with lexical relevance
    # ranking — best quality without an API key.
    search_fallback_provider: str | None = "bing_rss"
    baidu_search_api_key: str | None = None
    bing_search_api_key: str | None = None
    google_search_api_key: str | None = None
    google_search_engine_id: str | None = None
    tavily_api_key: str | None = None
    
    # Google Analytics configuration
    google_analytics_id: str | None = None

    # GitHub button on the login/landing page (client runtime config).
    # show_github_button: bool; github_repository_url: link the button opens.
    show_github_button: bool = False
    github_repository_url: str | None = None
    # Claw branding toggle (client runtime config)
    claw_enabled: bool = False

    # Auth configuration
    auth_provider: str = "password"  # "password", "none", "local"
    password_salt: str | None = None
    password_hash_rounds: int = 10
    password_hash_algorithm: str = "pbkdf2_sha256"
    local_auth_email: str = "admin@example.com"
    local_auth_password: str = "admin"
    
    # Email configuration
    email_host: str | None = None  # "smtp.gmail.com"
    email_port: int | None = None  # 587
    email_username: str | None = None
    email_password: str | None = None
    email_from: str | None = None
    
    # JWT configuration
    jwt_secret_key: str = "your-secret-key-here"
    jwt_algorithm: str = "HS256"
    jwt_access_token_expire_minutes: int = 30
    jwt_refresh_token_expire_days: int = 7
    
    # Extra headers for LLM requests (parsed from EXTRA_HEADERS env var, JSON)
    extra_headers: dict | None = None
    
    # SSL verification — False by default for custom/self-signed gateway compatibility
    # Set SSL_VERIFY=true only if your gateway has a valid public certificate
    ssl_verify: bool = False

    # Agent loop limits
    # Maximum number of plan steps the executor will run before
    # force-summarising. 0 = UNLIMITED (default): the loop runs until the
    # plan is genuinely complete — going from zero to a running server is
    # never cut short by an arbitrary counter (matches the reference
    # agent's behaviour). Set a positive number only to cap runaway spend.
    # env var: MAX_STEPS
    max_steps: int = 0

    # How many consecutive FAILED steps (failed steps, not iterations —
    # healthy work never counts) before the loop skips to SUMMARIZING.
    # This is a health guard against infinite retry spirals burning
    # credits, NOT an iteration limit: the in-loop nudges (strategy-change
    # advisories, loop detector) push self-correction long before it.
    # env var: MAX_CONSECUTIVE_FAILURES
    max_consecutive_failures: int = 10

    # Tool-loop rounds for delegated SUB-AGENTS (task_delegate).
    # 0 = UNLIMITED (default): a sub-agent finishes its subtask instead of
    # being cut mid-flight; it cannot ask the user anything anyway.
    # env var: NESTED_MAX_ITERATIONS
    nested_max_iterations: int = 0

    # Orchestration engine for the plan→execute→update agent loop.
    #   "langgraph" — PlanActGraphFlow: LangGraph StateGraph drives the SAME
    #                state machine (identical agents, prompts, events, guards).
    #   "custom"    — PlanActFlow: the original hand-rolled while-loop.
    # Both flows share every agent and emit the same event contract; the flag
    # only selects the loop driver. env var: AGENT_FLOW_ENGINE
    agent_flow_engine: str = "langgraph"

    # ── Context-overflow defense (provider error 1261) ──────────────────
    # Soft budget on the estimated serialized conversation size. Before
    # EVERY LLM call the agent estimates its memory size in characters;
    # above this limit it compacts progressively (stub old tool results →
    # aggressive stub → drop old rounds) so the prompt never reaches the
    # provider's hard limit. ~280K chars ≈ 70-90K tokens — comfortably
    # below common 128K-token windows. 0 disables the proactive gate
    # (the in-flight 1261 emergency recovery still applies).
    # env var: AGENT_CONTEXT_SOFT_LIMIT_CHARS
    context_soft_limit_chars: int = 280_000

    # Hard cap on a single serialized tool result as it enters the LLM
    # context (ToolMessage.content). One giant browser_view / file_read /
    # search payload can otherwise dominate every later request. The raw
    # result stays intact on the ToolMessage artifact for the UI.
    # 0 disables the cap. env var: AGENT_TOOL_RESULT_MAX_CHARS
    tool_result_max_chars: int = 48_000

    # Extra instructions appended to all agent system prompts at runtime.
    # Useful for per-deployment persona customisation without editing code.
    # env var: EXTEND_SYSTEM_MESSAGE
    extend_system_message: str | None = None

    # MCP configuration
    mcp_config_path: str = "/home/runner/workspace/mcp.json"

    # ── Manus tool registry (v1.1 standard) ────────────────────────────────
    # When True, every model tool call is validated against the JSON registry
    # (backend/app/domain/services/manus_registry/registry.json) before
    # execution and routed through the MCP or Shell transport executor.
    # False restores the legacy direct-toolkit dispatch.
    manus_registry_enabled: bool = True
    # Directory holding the 16 allowlisted manus-* CLI executables inside the
    # sandbox (absolute paths enforced by the shell executor).
    # EMPTY = auto-resolved per host (Replit: /home/runner/manus_tools_bin,
    # z.ai: /home/z/manus_tools_bin, VPS: sibling of USER_HOME_ROOT) and
    # auto-deployed from the repo's canonical copy on first use — no
    # environment-specific default that crashes elsewhere. Set it explicitly
    # only to pin a nonstandard location.
    manus_tools_bin_dir: str = ""
    # Per-call timeout for shell-transport tools (coreutils `timeout`).
    manus_shell_timeout_seconds: int = 120
    # Bounded stdout/stderr size (chars) returned from shell tools.
    manus_shell_max_output_chars: int = 8000
    # ── Agent orchestrator contracts (agent_architecture_json v1.0) ────────
    # Identical (tool,args) calls allowed before LOOP_DETECTED (contract:
    # max_identical_calls=2).
    manus_max_identical_calls: int = 2
    # Consecutive identical failures before the loop stops with guidance.
    manus_max_identical_errors: int = 3
    # Failures of one shell COMMAND FAMILY (same leading binary after
    # cd-chain/wrapper stripping: npx X ≈ ./node_modules/.bin/X ≈ X) allowed
    # before ANY new call in that family is blocked with the last error
    # excerpt attached. Mutation-aware: a real state change between
    # attempts (npm install, file edit) resets the budget — that is a
    # legit fix-and-retry, not a loop.
    manus_family_failure_limit: int = 3
    # Executor-level auto-retries for RETRYABLE failures (timeout/transient)
    # before the failure reaches the model (contract: max_retries_per_call=2).
    manus_max_retries_per_call: int = 2
    # Pending confirmation TTL (contract: expire token rule).
    manus_confirmation_ttl_seconds: int = 600
    # ── Agent runtime contracts (agent_runtime_json v1.0) ──────────────────
    # Wall-clock budget per agent RUN in ms (runtime.config.json
    # agent.task_timeout_ms=900000). 0 disables the wall-clock guard.
    manus_task_timeout_ms: int = 900_000
    # Hard ceiling for ONE tool execution in seconds (gate level, all
    # transports). A hung tool (wedged browser init, dead MCP server) must
    # fail honestly instead of blocking the agent loop forever while the
    # user watches "thinking" with no progress. 0 disables the ceiling.
    manus_tool_timeout_seconds: float = 300.0
    # LLM context cap in messages (runtime.config.json
    # agent.context_max_messages=200) — oldest messages roll off first.
    agent_context_max_messages: int = 200
    # Duplicate-submission window in seconds: the SAME message text re-sent
    # to the same session within this window (double Enter / double click /
    # flaky client retry) is treated as a reconnect instead of a new turn —
    # it must never run the whole agent loop twice (reported bug: one send
    # produced two full replies 33 s apart).
    agent_duplicate_message_window_seconds: int = 120

    # Logging configuration
    log_level: str = "INFO"
    
    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        extra = "ignore"

    # pydantic-settings v2 reads bools from env naturally; keep the legacy
    # Config class for compatibility with existing deployments.
        
    def check_required_settings(self):
        """Validate configuration settings"""
        if not self.api_key:
            raise ValueError("API key is required")
        if self.jwt_secret_key == "your-secret-key-here":
            logger.warning(
                "JWT_SECRET_KEY is using the default insecure value. "
                "Set the JWT_SECRET_KEY environment variable to a strong random secret."
            )

@lru_cache()
def get_settings() -> Settings:
    """Get application settings"""
    settings = Settings()
    # Ensure OPENAI_API_KEY is always present in the process environment for
    # the OpenAI SDK / langchain-openai clients. On Replit the userenv vars
    # (API_KEY, …) are injected as real process env vars, but when the app is
    # run from a plain shell the credentials only live in the .env file that
    # pydantic-settings reads — they never reach os.environ, so any client
    # relying on the OPENAI_API_KEY env var would fail with
    # "The api_key client option must be set …".
    if not os.environ.get("OPENAI_API_KEY"):
        api_key_val = os.getenv("API_KEY") or settings.api_key
        if api_key_val:
            os.environ["OPENAI_API_KEY"] = api_key_val
    # EXTRA_HEADERS: prefer the pydantic-parsed value — pydantic-settings
    # reads it from BOTH the process environment and the .env file (JSON dict
    # field). Reading only os.environ here (the old behaviour) silently
    # dropped EXTRA_HEADERS on deployments that configure via .env file,
    # sending LLM requests without the required auth headers (HTTP 403).
    settings.extra_headers = settings.extra_headers or _parse_extra_headers()
    settings.check_required_settings()
    return settings


# Paths checked for z.ai internal API credentials (z-ai-web-dev-sdk layout).
_ZAI_CONFIG_PATHS = (
    "/etc/.z-ai-config",
    os.path.expanduser("~/.z-ai-config"),
)


def get_fallback_model_config() -> dict | None:
    """Resolve the fallback LLM provider configuration.

    Priority:
    1. Explicit FALLBACK_* environment variables (.env / Replit userenv).
    2. Auto-discovery of the z.ai internal API config
       (``/etc/.z-ai-config`` — the same credentials the z-ai SDK uses).

    Returns a dict with ``api_base``, ``api_key``, ``model_name`` and
    ``extra_headers`` ready for init_chat_model, or None when no fallback
    provider is available (e.g. deployed outside the z.ai environment without
    FALLBACK_* set — the agent then simply retries the primary provider).
    """
    settings = get_settings()
    if settings.fallback_api_base and settings.fallback_api_key:
        headers = {"X-Z-AI-From": "Z"}
        if settings.fallback_token:
            headers["X-Token"] = settings.fallback_token
        if settings.fallback_chat_id:
            headers["X-Chat-Id"] = settings.fallback_chat_id
        if settings.fallback_user_id:
            headers["X-User-Id"] = settings.fallback_user_id
        return {
            "api_base": settings.fallback_api_base,
            "api_key": settings.fallback_api_key,
            "model_name": settings.fallback_model_name or "glm-4.7",
            "extra_headers": headers,
        }

    for path in _ZAI_CONFIG_PATHS:
        try:
            with open(path, "r", encoding="utf-8") as f:
                cfg = json.load(f)
            if not (cfg.get("baseUrl") and cfg.get("apiKey")):
                continue
            headers = {"X-Z-AI-From": "Z"}
            if cfg.get("token"):
                headers["X-Token"] = cfg["token"]
            if cfg.get("chatId"):
                headers["X-Chat-Id"] = cfg["chatId"]
            if cfg.get("userId"):
                headers["X-User-Id"] = cfg["userId"]
            return {
                "api_base": cfg["baseUrl"],
                "api_key": cfg["apiKey"],
                "model_name": settings.fallback_model_name or "glm-4.7",
                "extra_headers": headers,
            }
        except (OSError, json.JSONDecodeError):
            continue
    return None
