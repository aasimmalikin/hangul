from typing import Literal
from pydantic import AliasChoices, Field
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
    # Vision (harness/media/vision.py): reads uploaded photos / screenshots.
    # Must be in providers.registry so its cost is charged to the user.
    vision_model: str = "gpt-5-mini"
    # Voice (harness/media/voice.py): speech-to-text for the mic / voice notes
    # and text-to-speech for spoken answers. Costs are charged to the user's
    # allowance at these approximate rates (VERIFY against OpenAI pricing).
    stt_model: str = "gpt-4o-mini-transcribe"
    tts_model: str = "gpt-4o-mini-tts"
    tts_voice: str = "coral"
    stt_usd_per_minute: float = 0.003
    tts_usd_per_1k_chars: float = 0.015
    # Reminder emails (harness/notify.py) via Resend -- the same account the web
    # app uses for sign-in links, so AUTH_RESEND_KEY / AUTH_EMAIL_FROM work too.
    # Unset = reminders are in-app only.
    resend_api_key: str | None = Field(default=None, validation_alias=AliasChoices("resend_api_key", "auth_resend_key"))
    email_from: str | None = Field(default=None, validation_alias=AliasChoices("email_from", "auth_email_from"))
    app_url: str = "http://localhost:3000"     # links in emails
    # Billing (harness/billing) via Dodo Payments, the merchant of record.
    # Unset API key = billing off: no plan checks, every model open (dev).
    dodo_api_key: str | None = None
    dodo_webhook_secret: str | None = None    # whsec_… from the Dodo dashboard
    dodo_product_plus: str | None = None      # pdt_… subscription product
    dodo_product_pro: str | None = None
    dodo_product_topup: str | None = None     # pdt_… one-time product
    dodo_test_mode: bool = True               # test.dodopayments.com vs live.dodopayments.com
    billing_return_url: str = "http://localhost:3000/billing"   # where checkout sends the buyer back
    # Allowances and credits are dollars of MODEL cost (registry prices), not
    # what the user pays; the gap is the margin for tools, embeddings, tax.
    billing_allowance_free: float = 0.50       # per calendar month
    billing_allowance_plus: float = 8.00       # per billing period
    billing_allowance_pro: float = 40.00
    billing_topup_credit_usd: float = 5.00     # credit granted per top-up purchase
    # Cap on what ALL free users together may spend per UTC month (dollars of
    # model cost). Protects the prepaid OpenAI balance that paying users rely
    # on from a surge of free sign-ups. Unset = no cap.
    billing_free_pool_usd: float | None = None

def get_settings() -> Settings:
    """ Retrieve the application settings, cached for performance. """
    return Settings()
