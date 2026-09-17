import logging
from pathlib import Path
from contextlib import asynccontextmanager
from fastapi import FastAPI
from harness.logging import configure_logging, log
from harness.config import get_settings
from harness.api.routes import ask, health, observability, upload, quality, approve, ask_stream
from harness.mcp.manager import MCPManager
from harness.api.routes.ask import _registry
from harness.api.routes import memory, episodes

settings = get_settings()
configure_logging(settings.log_level)

_mcp_manager: MCPManager | None = None

@asynccontextmanager

async def lifespan(app: FastAPI):
    global _mcp_manager
    log.info("Starting up", app_name = settings.app_name, env = settings.environment)
    
    Path("data/sessions").mkdir(parents = True, exist_ok = True)

    _mcp_manager = MCPManager()

    for name, command, args in [
        #("git", "uvx", ["mcp-server-git", "--repository", "."]),
        ("filesystem", "npx", ["-y", "@modelcontextprotocol/server-filesystem", "docs", "data/sessions"])
    ]:
      try:
        await _mcp_manager.add_server(name, command, args, _registry)
      except Exception as e:
        log.warning("MCP connect failed", error = str(e))
    
    log.info("tools ready", tools=[t.name for t in _registry.list()])

    yield

    if _mcp_manager is not None:
        await _mcp_manager.close()
    log.info("harness shutting down")

def create_app() -> FastAPI:
    app = FastAPI(title = settings.app_name, lifespan = lifespan)
    app.include_router(ask.router)
    app.include_router(health.router)
    app.include_router(observability.router)
    app.include_router(upload.router)
    app.include_router(quality.router)
    app.include_router(approve.router)
    app.include_router(ask_stream.router)
    app.include_router(memory.router)
    app.include_router(episodes.router)
    return app

app = create_app()