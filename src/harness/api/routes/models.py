"""GET /models — the selectable models, their prices and effort options."""

from fastapi import APIRouter, Depends

from harness.api.auth import get_current_user
from harness.providers.registry import list_models, resolve

router = APIRouter()


@router.get("/models")
async def models(user: dict = Depends(get_current_user)) -> dict:
    default_spec, default_effort = resolve(None, None)
    return {
        "default": {"model": default_spec.id, "effort": default_effort},
        "models": [s.to_dict() for s in list_models()],
    }
