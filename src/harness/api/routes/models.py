"""GET /models — the selectable models, their prices and effort options,
and which of them the caller's plan leaves locked (harness.billing)."""

import asyncio

from fastapi import APIRouter, Depends

from harness.api.auth import get_current_user
from harness.billing import entitlements
from harness.billing.plans import cheapest_plan_for
from harness.providers.registry import list_models, resolve

router = APIRouter()


@router.get("/models")
async def models(user: dict = Depends(get_current_user)) -> dict:
    if not entitlements.billing_enabled():
        default_spec, default_effort = resolve(None, None)
        return {
            "default": {"model": default_spec.id, "effort": default_effort},
            "models": [{**s.to_dict(), "locked": False} for s in list_models()],
            "plan": None,
        }
    st = await asyncio.to_thread(entitlements.standing, user["user_id"])
    plan = st.plan
    # the default a request with no model would get on this plan
    default_spec, default_effort = entitlements.resolve_for_user(
        user["user_id"], None, None, check_balance=False, plan_standing=st)
    out = []
    for s in list_models():
        locked = not plan.allows_model(s)
        out.append({**s.to_dict(), "locked": locked,
                    "plan_needed": cheapest_plan_for(s).id if locked else None,
                    "efforts": [e for e in s.efforts if plan.allows_effort(e)]})
    return {
        "default": {"model": default_spec.id, "effort": default_effort},
        "models": out,
        "plan": plan.id,
        "max_effort": plan.max_effort,
    }
