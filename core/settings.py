from functools import lru_cache
from typing import Optional, Dict, Any
from pathlib import Path
import logging
import os
import sys
from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
import structlog

logger = structlog.get_logger()

class AppSettings(BaseSettings):
    environment: str = "development"
    dev_mode: bool = False
    mcp_auth_secret: Optional[str] = None
    mcp_token_expiry: int = 300
    mcp_auth_metrics: bool = True
    mcp_auth_log_level: str = "INFO"
    bus_backend: str = "inproc"
    bus_redis_url: str = "redis://localhost:6379/0"
    bus_max_queue_size: int = 1000
    bus_concurrency_limit: int = 10
    database_url: str = "sqlite:///./app/data.db"
    data_db: Optional[str] = None
    openai_api_key: Optional[str] = None
    openai_base_url: Optional[str] = None
    openrouter_api_key: Optional[str] = None
    openrouter_base_url: Optional[str] = None
    openrouter_model: str = "deepseek/deepseek-r1-0528:free"
    gemini_api_key: Optional[str] = None
    gemini_base_url: Optional[str] = None
    summarizer_model: Optional[str] = None
    alerts_cap_secret: str = "dev-secret"
    ui_llm_max_tokens: Optional[int] = None
    llm_price_map: Optional[str] = None
    log_level: str = "INFO"
    log_structured: bool = True
    service_host: str = "0.0.0.0"
    service_port: int = 8000
    use_mcp: bool = False
    use_langchain: bool = False
    ui_require_login: bool = False
    
    model_config = SettingsConfigDict(env_file=".env", extra="allow", case_sensitive=False)

    @model_validator(mode='after')
    def validate_config(self) -> 'AppSettings':
        # Auth secret validation
        if not self.mcp_auth_secret:
            if self.environment == "development":
                import secrets
                self.mcp_auth_secret = secrets.token_urlsafe(32)
                logger.warning("generated_dev_auth_secret", msg="Set MCP_AUTH_SECRET in your environment for stability.")
            else:
                raise ValueError("MCP_AUTH_SECRET is required in production")
        elif len(self.mcp_auth_secret) < 32:
            raise ValueError("MCP_AUTH_SECRET must be at least 32 characters for security")

        # Bus validation
        if self.bus_backend not in ("inproc", "redis"):
            raise ValueError(f"BUS_BACKEND must be 'inproc' or 'redis', got '{self.bus_backend}'")
        
        if self.bus_backend == "redis" and not self.bus_redis_url.startswith("redis://"):
            raise ValueError("BUS_REDIS_URL must start with 'redis://' when using Redis backend")

        # Numeric ranges
        if not (1 <= self.mcp_token_expiry <= 86400):
            raise ValueError("MCP_TOKEN_EXPIRY must be between 1 and 86400 seconds")
        
        if not (1 <= self.bus_max_queue_size <= 100000):
            raise ValueError("BUS_MAX_QUEUE_SIZE must be between 1 and 100000")
        
        if not (1 <= self.bus_concurrency_limit <= 1000):
            raise ValueError("BUS_CONCURRENCY_LIMIT must be between 1 and 1000")

        # Log levels
        valid_log_levels = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
        if self.log_level.upper() not in valid_log_levels:
            raise ValueError(f"LOG_LEVEL must be one of {valid_log_levels}")
        if self.mcp_auth_log_level.upper() not in valid_log_levels:
            raise ValueError(f"MCP_AUTH_LOG_LEVEL must be one of {valid_log_levels}")

        return self

    @property
    def debug(self) -> bool:
        return self.dev_mode or self.environment.lower() == "development"

    def setup_logging(self):
        """Configure structlog and standard logging."""
        shared_processors = [
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.StackInfoRenderer(),
            structlog.dev.set_exc_info,
            structlog.processors.TimeStamper(fmt="iso"),
        ]

        if self.log_structured:
            processors = shared_processors + [
                structlog.processors.dict_tracebacks,
                structlog.processors.JSONRenderer(),
            ]
        else:
            processors = shared_processors + [
                structlog.dev.ConsoleRenderer(),
            ]

        structlog.configure(
            processors=processors,
            wrapper_class=structlog.make_filtering_bound_logger(getattr(logging, self.log_level.upper())),
            context_class=dict,
            logger_factory=structlog.PrintLoggerFactory(),
            cache_logger_on_first_use=True,
        )

        # Configure standard logging to redirect to structlog
        logging.basicConfig(format="%(message)s", stream=sys.stdout, level=getattr(logging, self.log_level.upper()))
        
        # Configure auth logging specifically
        auth_logger = logging.getLogger("mcp.auth")
        auth_logger.setLevel(getattr(logging, self.mcp_auth_log_level.upper()))

    def resolve_app_db(self) -> Path:
        root = Path(__file__).resolve().parents[1]
        base = self.data_db or os.getenv("DATA_DB")
        if base:
            p = Path(base)
            return p if p.is_absolute() else root / p
        return root / "app" / "data.db"

    def resolve_market_db(self) -> Path:
        root = Path(__file__).resolve().parents[1]
        return root / "data" / "market.db"


@lru_cache
def get_settings() -> AppSettings:
    settings = AppSettings()
    settings.setup_logging()
    return settings

# Backward compatibility helpers
def init_config() -> AppSettings:
    return get_settings()

def get_config() -> AppSettings:
    return get_settings()
