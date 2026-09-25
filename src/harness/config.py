from typing import Literal
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    """Application configuration settings."""
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    app_name: str = "hangul-harness"
    environment: Literal["dev", "prod"] = "dev"
    log_level: str = "INFO"
    openai_api_key: str | None = None
    model: str = "gpt-5.5"           # default; must be a key of providers.registry.MODELS
    default_effort: str = "medium"   # default reasoning effort when the request sets none
    tavily_api_key: str | None = None
    database_url: str = "postgresql+psycopg://agentic:agentic@localhost:5432/hangul_harness"
    redis_url: str = "redis://localhost:6379/0"
    jwt_secret: str = "dev-secret-change-in-production"
    jwt_algorithm: str = "HS256"
    # Token vault (see harness/vault). Unset master key = vault disabled.
    vault_master_key: str | None = None      # Fernet key: python -c "from cryptography.fernet import Fernet;print(Fernet.generate_key().decode())"
    vault_grant_ttl_s: int = 300             # lifetime of a grant handed to a tool / MCP server
    vault_proxy_timeout_s: float = 30.0
    vault_max_body_bytes: int = 1_000_000
    vault_public_url: str = "http://127.0.0.1:8000"   # how MCP subprocesses reach /vault/proxy
    # Scheduled tasks (harness/scheduler): run due tasks every minute in-process.
    scheduler_enabled: bool = True
    # Google OAuth client (same values the web app uses for sign-in); the
    # backend needs them to refresh Workspace access tokens for the bundle.
    auth_google_id: str | None = None
    auth_google_secret: str | None = None
    # Prompt-injection defence (harness/security). The pattern detector is
    # always on; the model-based screen of tool results is opt-in (cost).
    security_llm_screen: bool = False
    security_screen_model: str = "gpt-4.1-mini"
    security_offender_limit: int = 5            # flagged inputs per window before throttling
    security_offender_window_s: int = 600
    # Admin console. Only these Google-verified emails may call /admin/*; the
    # allowlist lives here, on the backend, so the web tier cannot widen it.
    admin_emails: str = "aasimmallikk@gmail.com"      # comma-separated
    admin_max_auth_age_s: int = 12 * 60 * 60          # the Google sign-in must be this recent
    admin_ip_allowlist: str = ""                      # comma-separated CIDRs; empty = any client

def get_settings() -> Settings:
    """ Retrieve the application settings, cached for performance. """
    return Settings()
