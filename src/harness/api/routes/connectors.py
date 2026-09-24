"""GET /connectors -- what the "+ → Connectors" menu can offer. Public: it
only says which connectors exist, never what a user has enabled."""

from fastapi import APIRouter

from harness.connectors import available

router = APIRouter()


@router.get("/connectors")
async def list_connectors() -> list[dict]:
    return available()
