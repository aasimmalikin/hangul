"""Per-user integrations: what the signed-in person has connected.

GET /integrations             -> {"google": {"connected": bool, "products": [...]},
                                  "apps": {"github": bool, "notion": bool, "slack": bool}}
DELETE /integrations/google   -> forget the stored Google refresh token
POST /integrations/apps/{app} -> save a GitHub / Notion / Slack token in the vault
DELETE /integrations/apps/{app} -> remove it
"""

import asyncio

from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import update

from harness.api.auth import get_current_user
from harness.db.base import SessionLocal
from harness.db.models import Account
from harness.integrations.google_oauth import GoogleNotConnected, google_tokens, scopes_for
from harness.mcp.manager import current as mcp_current

router = APIRouter()


WORK_APPS = ("github", "notion", "slack")
# one cheap read that proves a pasted token works before it is kept
APP_CHECKS = {"github": ("/user", {}), "notion": ("/v1/users/me", {"Notion-Version": "2022-06-28"}),
              "slack": ("/api/auth.test", {})}


async def apps_status(user_id: str) -> dict[str, bool]:
    from harness.vault import current as current_vault
    vault = current_vault()
    if vault is None:
        return {a: False for a in WORK_APPS}
    try:
        consented = await vault.consented_providers(user_id)
        creds = {c.provider for c in await vault.list_credentials(user_id) if c.user_id is not None}
    except Exception:  # noqa: BLE001 - a status read must not fail the page
        return {a: False for a in WORK_APPS}
    return {a: a in consented and a in creds for a in WORK_APPS}


@router.get("/integrations")
async def integrations(user: dict = Depends(get_current_user)) -> dict:
    google = await google_tokens().status(user["user_id"])
    # what Connect Google asks for: without Gmail and Drive unless the account is on the restricted list
    google["scopes"] = scopes_for(google.get("restricted", True))
    return {"google": google, "apps": await apps_status(user["user_id"])}


class AppToken(BaseModel):
    token: str = Field(min_length=8, max_length=4000)


@router.post("/integrations/apps/{app}")
async def connect_app(app: str, req: AppToken, user: dict = Depends(get_current_user)) -> dict:
    """Store the token (encrypted) with a standing consent. Writes still pause
    for approval on every call (their tools are DESTRUCTIVE)."""
    from harness.vault import current as current_vault
    if app not in WORK_APPS:
        raise HTTPException(status_code=404, detail="Unknown app.")
    from harness.connectors.registry import BUILTIN
    if BUILTIN[app].hidden:
        raise HTTPException(status_code=404, detail=f"{BUILTIN[app].label} is no longer offered.")
    vault = current_vault()
    if vault is None:
        raise HTTPException(status_code=503, detail="The token vault isn't set up on this server (VAULT_MASTER_KEY).")
    uid = user["user_id"]
    token = req.token.strip()
    for old in [c for c in await vault.list_credentials(uid) if c.provider == app and c.user_id is not None]:
        await vault.revoke_credential(uid, old.id)              # one token per app: replace
    rec = await vault.add_credential(user_id=uid, provider=app, secret=token, label=f"{app} (connected in Hangul)")
    await vault.grant_consent(user_id=uid, provider=app, ttl=timedelta(days=365), allow_write=True)
    path, headers = APP_CHECKS[app]
    ok, why = True, ""
    try:
        resp = await vault.call(subject=uid, provider=app, method="GET", path=path, headers=headers)
        body = resp.body or ""
        if resp.status >= 400 or (app == "slack" and '"ok":false' in body.replace(" ", "")):
            ok, why = False, f"{app.capitalize()} refused that token ({resp.status})."
    except Exception as e:  # noqa: BLE001
        ok, why = False, f"Couldn't check the token with {app.capitalize()} ({type(e).__name__})."
    if not ok:
        await vault.revoke_credential(uid, rec.id)
        raise HTTPException(status_code=400, detail=why + " Check you copied the whole token.")
    return {"connected": True, "app": app}


@router.delete("/integrations/apps/{app}")
async def disconnect_app(app: str, user: dict = Depends(get_current_user)) -> dict:
    from harness.vault import current as current_vault
    if app not in WORK_APPS:
        raise HTTPException(status_code=404, detail="Unknown app.")
    vault = current_vault()
    n = 0
    if vault is not None:
        for c in [c for c in await vault.list_credentials(user["user_id"]) if c.provider == app and c.user_id is not None]:
            n += bool(await vault.revoke_credential(user["user_id"], c.id))
    return {"disconnected": n > 0}


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
