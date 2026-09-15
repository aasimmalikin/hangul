from fastapi import APIRouter, Depends

from harness.api.auth import require_admin
from harness.api.routes.ask import _trace_store

# Traces carry every user's questions and tool arguments; metrics carry
# spend. Operator-only.
router = APIRouter(dependencies=[Depends(require_admin)])


@router.get("/traces")
async def traces(n: int = 20):
    return {"traces": _trace_store.recent(min(max(n, 1), 200))}


@router.get("/metrics")
async def metrics():
    return _trace_store.metrics()
