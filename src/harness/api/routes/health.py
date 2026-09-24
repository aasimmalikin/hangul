from fastapi import APIRouter

from harness.mcp import manager as mcp_manager

router = APIRouter()

@router.get("/healthz")
async def healthz()->dict:
    # status stays "ok" even when an MCP server is down: that degrades the
    # tool set, it does not take the API down (smoke_test.sh only checks 200)
    mgr = mcp_manager.current()
    return {
        "status": "ok",
        "mcp": [s.as_dict() for s in mgr.status()] if mgr is not None else [],
    }
