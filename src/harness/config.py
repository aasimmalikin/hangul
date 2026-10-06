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
    # "Auto" (providers/router.py): the model for quick / everyday / write / deep messages,
    # each falling back down the ladder to what the user's plan includes
    auto_fast_model: str = "gpt-5.6-luna"
    auto_everyday_model: str = "gpt-5.6-luna"     # lookups, summaries, reading mail and calendar
    auto_balanced_model: str = "gpt-5.6-terra"    # writing: drafts and replies the user will send
    auto_best_model: str = "gpt-5.6-sol"
    # costs besides model tokens (billing/meter.py), charged to the user who caused them
    embedding_usd_per_m: float = 0.02         # text-embedding-3-small, per 1M tokens
    web_search_usd: float = 0.008             # one Tavily basic search (pay-as-you-go credit)
    summary_model: str = "gpt-5.6-luna"       # conversation compaction: bookkeeping, so the cheap model
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
    # Image generation (tools/builtin/images.py), Pro plan. Charged per image
    # at approximate list prices (VERIFY on OpenAI's pricing page).
    image_model: str = "gpt-image-1"
    image_default_quality: str = "medium"
    # Maps (tools/builtin/maps.py): OpenStreetMap's Nominatim asks every app to
    # identify itself with a contact address in the User-Agent.
    maps_contact_email: str | None = None
    # Reminder emails (harness/notify.py) via Resend -- the same account the web
    # app uses for sign-in links, so AUTH_RESEND_KEY / AUTH_EMAIL_FROM work too.
    # Unset = reminders are in-app only.
    resend_api_key: str | None = Field(default=None, validation_alias=AliasChoices("resend_api_key", "auth_resend_key"))
    email_from: str | None = Field(default=None, validation_alias=AliasChoices("email_from", "auth_email_from"))
    app_url: str = "http://localhost:3000"     # links in emails
    # WhatsApp (harness/whatsapp) via Meta's Cloud API. Off until both the token
    # and the phone number id are set. The token is imported into the vault at
    # startup (like TAVILY_API_KEY) and never read anywhere else.
    whatsapp_access_token: str | None = None          # a System User's permanent token
    whatsapp_phone_number_id: str | None = None       # sends go to /<version>/<this>/messages
    whatsapp_business_number: str | None = None       # the number users message, e.g. +919876543210 (wa.me links)
    whatsapp_app_secret: str | None = None            # checks X-Hub-Signature-256 on every webhook delivery
    whatsapp_verify_token: str | None = None          # any long random string; Meta echoes it once to confirm the webhook
    whatsapp_api_version: str = "v23.0"
    # approved templates for messages Hangul starts outside the 24-hour window
    whatsapp_template_reminder: str = "reminder"      # body: "⏰ Reminder: {{1}}"
    whatsapp_template_brief: str = "morning_brief"    # body: "Good morning {{1}}! Your brief is ready. Reply to see it."
    # optional: a scheduled task's approval outside the 24-hour window, with quick-reply buttons
    # Approve / Reject. Body: "Hangul needs your OK for {{1}}: {{2}}". Unset = the brief template,
    # and the Approve / Reject buttons follow the user's reply.
    whatsapp_template_approval: str = ""
    whatsapp_template_language: str = "en"
    whatsapp_usd_per_message: float = 0.0016          # Meta's India utility/service rate incl. GST, charged to the user
    whatsapp_link_code_ttl_s: int = 15 * 60
    # Web Push (harness/push.py): notifications on the user's phone or computer from
    # the installed app or the browser, even when Hangul is closed. Off until both
    # keys are set; make a pair with `python -m harness.push keys`.
    vapid_public_key: str | None = None       # base64url P-256 point (the browser's applicationServerKey)
    vapid_private_key: str | None = None      # base64url raw 32-byte key; never leaves the server
    vapid_subject: str | None = None          # mailto:/https: contact for push services; default mailto:<email_from>
    # Billing (harness/billing) via Dodo Payments, the merchant of record.
    # Unset API key = billing off: no plan checks, every model open (dev).
    dodo_api_key: str | None = None
    dodo_webhook_secret: str | None = None    # whsec_… from the Dodo dashboard
    dodo_product_plus: str | None = None      # pdt_… subscription product
    dodo_product_pro: str | None = None
    dodo_product_topup: str | None = None     # pdt_… one-time product
    # yearly plans (2 months free) and Indian plans (priced in rupees, UPI AutoPay);
    # any left unset falls back to the international monthly product
    dodo_product_plus_annual: str | None = None
    dodo_product_pro_annual: str | None = None
    dodo_product_plus_in: str | None = None
    dodo_product_pro_in: str | None = None
    dodo_product_plus_in_annual: str | None = None
    dodo_product_pro_in_annual: str | None = None
    dodo_test_mode: bool = True               # test.dodopayments.com vs live.dodopayments.com
    billing_return_url: str = "http://localhost:3000/billing"   # where checkout sends the buyer back
    # Allowances and credits are dollars of MODEL cost (registry prices), not
    # what the user pays; the gap is the margin for tools, embeddings, tax.
    billing_allowance_free: float = 0.25       # per calendar month
    billing_allowance_plus: float = 8.00       # per billing period
    billing_allowance_pro: float = 40.00
    # Indian prices (₹499 / ₹1,499) are about a quarter of $20 / $100 after GST
    # and fees, so they include a smaller monthly allowance
    billing_allowance_plus_in: float = 2.00
    billing_allowance_pro_in: float = 6.00
    billing_trial_days: int = 7                # Plus trial at checkout (0 = no trial); card authorised up front
    billing_allowance_trial: float = 2.00      # allowance while trialling, before the first real charge
    # "about N messages left": the allowance divided by the average cost of a run
    # over the last 30 days, or by this when there are too few runs to average
    billing_usd_per_message: float = 0.01
    billing_topup_credit_usd: float = 5.00     # credit granted per top-up purchase
    # Cap on what ALL free users together may spend per UTC month (dollars of
    # model cost). Protects the prepaid OpenAI balance that paying users rely
    # on from a surge of free sign-ups. Unset = no cap.
    billing_free_pool_usd: float | None = None

def get_settings() -> Settings:
    """ Retrieve the application settings, cached for performance. """
    return Settings()
