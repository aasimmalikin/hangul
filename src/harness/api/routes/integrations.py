"""Per-user integrations: what the signed-in person has connected.

GET /integrations             -> {"google": {"connected": bool, "products": [...]}}
DELETE /integrations/google   -> forget the stored Google refresh token
"""

import asyncio

from fastapi import APIRouter, Depends
from sqlalchemy import update

from harness.api.auth import get_current_user
from harness.db.base import SessionLocal
from harness.db.models import Account
from harness.integrations.google_oauth import ALL_SCOPES, GoogleNotConnected, google_tokens
from harness.mcp.manager import current as mcp_current

router = APIRouter()


@router.get("/integrations")
async def integrations(user: dict = Depends(get_current_user)) -> dict:
    google = await google_tokens().status(user["user_id"])
    google["scopes"] = list(ALL_SCOPES)
    return {"google": google}


def _forget_google(user_id: str) -> int:
    with SessionLocal() as s:
        n = s.execute(update(Account).where(Account.userId == int(user_id), Account.provider == "google")
                      .values(refresh_token=None, access_token=None, scope=None)).rowcount
        s.commit()
        return n


@router.delete("/integrations/google")
async def disconnect_google(user: dict = Depends(get_current_user)) -> dict:
    """Drop the refresh token (the user should also revoke at myaccount.google.com/permissions)
    and close any open Workspace MCP sessions for this user."""
    n = await asyncio.to_thread(_forget_google, user["user_id"])
    google_tokens().forget(user["user_id"])
    mgr = mcp_current()
    if mgr is not None:
        for key in [k for k in list(mgr._user_clients) if k[1] == user["user_id"]]:
            client = mgr._user_clients.pop(key)
            mgr._user_last_used.pop(key, None)
            await client.aclose()
    return {"disconnected": n > 0}


@router.get("/integrations/google/check")
async def check_google(user: dict = Depends(get_current_user)) -> dict:
    """Diagnostic for the Google Workspace connector (REST): the token's scopes
    and one cheap read per product, with Google's actual reply on failure."""
    import httpx
    out: dict = {"token": None, "servers": []}
    try:
        tok = await google_tokens().access_token(user["user_id"])
    except GoogleNotConnected as e:
        out["token"] = f"failed: {e}"
        return out
    probes = [
        ("gmail", "https://gmail.googleapis.com/gmail/v1/users/me/profile", {}),
        ("calendar", "https://www.googleapis.com/calendar/v3/users/me/calendarList", {"maxResults": 1}),
        ("drive", "https://www.googleapis.com/drive/v3/about", {"fields": "user(emailAddress)"}),
        ("docs", "https://www.googleapis.com/drive/v3/files",
         {"q": "mimeType='application/vnd.google-apps.document'", "pageSize": 1, "fields": "files(id,name)"}),
    ]
    async with httpx.AsyncClient(timeout=15.0, headers={"Authorization": f"Bearer {tok}"}) as c:
        try:
            r = await c.get("https://www.googleapis.com/oauth2/v3/tokeninfo", params={"access_token": tok}, headers={"Authorization": ""})
            out["token"] = {"status": r.status_code, **({k: v for k, v in r.json().items() if k in ("scope", "expires_in", "aud")}
                                                       if r.status_code == 200 else {"body": r.text[:200]})}
        except httpx.HTTPError as e:
            out["token"] = f"tokeninfo unreachable: {type(e).__name__}"
        for name, url, params in probes:
            try:
                r = await c.get(url, params=params)
                body = r.text[:300]
                if r.status_code == 200:
                    try:
                        j = r.json()
                        body = (j.get("emailAddress") or (j.get("user") or {}).get("emailAddress")
                                or (f"{len(j.get('items', []))} calendar(s)" if "items" in j else None)
                                or (f"{len(j.get('files', []))} doc(s) visible" if "files" in j else None) or body)
                    except ValueError:
                        pass
                out["servers"].append({"name": name, "url": url, "status": r.status_code, "body": str(body)})
            except httpx.HTTPError as e:
                out["servers"].append({"name": name, "url": url, "status": None, "body": f"{type(e).__name__}: {e}"[:300]})
    return out
