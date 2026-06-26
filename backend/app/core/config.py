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
    
    # MongoDB configuration
    mongodb_uri: str = "mongodb://mongodb:27017"
    mongodb_database: str = "dzeck"
    mongodb_username: str | None = None
    mongodb_password: str | None = None
    
    # Redis configuration
    redis_host: str = "redis"
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
    search_provider: str | None = "bing_web"  # "baidu", "baidu_web", "google", "bing", "bing_web", "tavily"
    baidu_search_api_key: str | None = None
    bing_search_api_key: str | None = None
    google_search_api_key: str | None = None
    google_search_engine_id: str | None = None
    tavily_api_key: str | None = None
    
    # Google Analytics configuration
    google_analytics_id: str | None = None

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
    
    # SSL verification — set SSL_VERIFY=false only for custom gateways with self-signed certs
    ssl_verify: bool = True

    # MCP configuration
    mcp_config_path: str = "/home/runner/workspace/mcp.json"
    
    # Logging configuration
    log_level: str = "INFO"
    
    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        extra = "ignore"
        
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
    if not os.environ.get("OPENAI_API_KEY"):
        api_key_val = os.getenv("API_KEY")
        if api_key_val:
            os.environ["OPENAI_API_KEY"] = api_key_val
    settings = Settings()
    settings.extra_headers = _parse_extra_headers()
    settings.check_required_settings()
    return settings 
