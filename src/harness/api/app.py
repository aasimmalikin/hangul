import logging
import asyncio
from pathlib import Path
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from harness.logging import configure_logging, log
from harness.config import get_settings
from harness.db.base import warm_pool
from harness.api.routes import ask, health, observability, upload, quality, approve, ask_stream
from harness.mcp.config import load_server_configs
from harness.mcp.manager import MCPManager, set_current as set_mcp_manager
from harness.api.routes.ask import _registry
from harness.api.routes import memory, episodes, models, vault as vault_routes, admin, connectors, integrations, settings as settings_routes, billing as billing_routes, personal as personal_routes, voice as voice_routes, files as files_routes, today as today_routes, whatsapp as whatsapp_routes, kept as kept_routes, push as push_routes
from harness.api.routes import approval_links as approval_link_routes, conversations
from harness import scheduler
from harness.providers.base import ModelUnavailable
from harness.providers.registry import get_model
from harness.vault.bootstrap import build_vault, shutdown_vault
from harness.security import SecurityGuard, set_guard
from harness.security.classifier import OpenAIInjectionClassifier

settings = get_settings()
configure_logging(settings.log_level)

_mcp_manager: MCPManager | None = None

@asynccontextmanager

async def lifespan(app: FastAPI):
    global _mcp_manager
    log.info("Starting up", app_name = settings.app_name, env = settings.environment,
             model = settings.model, default_effort = settings.default_effort)
    if settings.environment == "prod" and (settings.jwt_secret == "dev-secret-change-in-production"
                                           or len(settings.jwt_secret) < 32):
        # the default is public: anyone could mint a token for any user
        raise RuntimeError("JWT_SECRET is the development default (or shorter than 32 characters). "
                           "Set a long random JWT_SECRET, the same value as the web app's FASTAPI_JWT_SECRET.")
    if get_model(settings.model) is None:
        # Every /ask without an explicit model would 422 and cost would be 0.
        log.error("settings.model is not in providers.registry.MODELS", model = settings.model)

    Path("data/sessions").mkdir(parents = True, exist_ok = True)

    # open the DB pool now (bounded) so the first page load does not pay ~5 s per connection
    try:
        n = await asyncio.wait_for(asyncio.to_thread(warm_pool), timeout=30)
        log.info("db pool warmed", connections=n)
    except TimeoutError:
        log.warning("db pool warm-up timed out; continuing")

    # prompt-injection defence: pattern detector always; model screen when configured
    classifier = None
    if settings.security_llm_screen:
        classifier = OpenAIInjectionClassifier(settings.security_screen_model, settings.openai_api_key)
    set_guard(SecurityGuard(classifier=classifier, offender_limit=settings.security_offender_limit,
                            offender_window_s=settings.security_offender_window_s))
    log.info("security guard ready", llm_screen=settings.security_llm_screen)

    # the vault first: MCP servers may reference "vault:<provider>" in their config.
    # Bounded: a stalled database must not keep the server from ever serving.
    try:
        await asyncio.wait_for(build_vault(settings, audit=ask._audit), timeout=45)
    except TimeoutError:
        log.error("vault startup timed out (database unreachable?); continuing without the vault")

    try:
        _mcp_manager = MCPManager(load_server_configs())
    except ValueError as e:
        # a bad servers.yaml must not take the API down; run with no MCP tools
        log.error("MCP config invalid, starting without MCP servers", error=str(e))
        _mcp_manager = MCPManager()
    set_mcp_manager(_mcp_manager)
    try:
        await asyncio.wait_for(_mcp_manager.connect_all(), timeout=90)   # per-server failures are logged, never raised
    except TimeoutError:
        log.error("MCP startup timed out; servers left in their current state")
    _mcp_manager.register_into(_registry)
    for alert in _mcp_manager.alerts:
        log.warning("MCP shadowing", alert=alert)

    log.info("tools ready", tools=[t.name for t in _registry.list()],
             mcp=[st.as_dict() for st in _mcp_manager.status()])

    scheduler_task = scheduler.start() if settings.scheduler_enabled else None
    if scheduler_task is not None:
        # not replica-safe: a second server with it on would run every due task twice
        log.info("scheduler on: run exactly one API server with SCHEDULER_ENABLED=true")
    if settings.dodo_api_key and settings.billing_free_pool_usd is None:
        log.warning("billing is on but BILLING_FREE_POOL_USD is unset: free users' spend is uncapped. "
                    "Set a monthly cap before launch.")

    yield

    if scheduler_task is not None:
        scheduler_task.cancel()
    if _mcp_manager is not None:
        await _mcp_manager.aclose()
        set_mcp_manager(None)
    await shutdown_vault()
    log.info("harness shutting down")

def create_app() -> FastAPI:
    app = FastAPI(title = settings.app_name, lifespan = lifespan)

    @app.exception_handler(ModelUnavailable)
    async def _model_unavailable(request: Request, exc: ModelUnavailable):
        # a sentence the chat can show, not a bare 500 (or the vendor's "add credits" text)
        return JSONResponse(status_code=503, content={"detail": str(exc)},
                            headers={"X-Reason": f"model_{exc.reason}", "Retry-After": "60"})

    app.include_router(ask.router)
    app.include_router(health.router)
    app.include_router(observability.router)
    app.include_router(upload.router)
    app.include_router(quality.router)
    app.include_router(approve.router)
    app.include_router(approval_link_routes.router)
    app.include_router(ask_stream.router)
    app.include_router(memory.router)
    app.include_router(episodes.router)
    app.include_router(conversations.router)
    app.include_router(models.router)
    app.include_router(vault_routes.router)
    app.include_router(admin.router)
    app.include_router(connectors.router)
    app.include_router(integrations.router)
    app.include_router(settings_routes.router)
    app.include_router(billing_routes.router)
    app.include_router(personal_routes.router)
    app.include_router(voice_routes.router)
    app.include_router(files_routes.router)
    app.include_router(today_routes.router)
    app.include_router(whatsapp_routes.router)
    app.include_router(kept_routes.router)
    app.include_router(push_routes.router)
    return app

app = create_app()