"""Token vault endpoints.

Everything under /vault is scoped to the signed-in user and never returns a
secret -- credentials come back as label + fingerprint only. The two proxy
routes are the exception to JWT auth: they are authenticated by the grant
token alone, because MCP subprocesses have no user session and the grant
already binds user, provider, method set and TTL."""

import asyncio
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, Field, SecretStr

from harness.api.auth import get_current_user
from harness.vault import current as current_vault
from harness.vault.proxy import ProxyError
from harness.vault.vault import Vault, VaultError, VaultUnavailable

router = APIRouter()

MAX_CONSENT_HOURS = 24 * 30


def _vault() -> Vault:
    v = current_vault()
    if v is None:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "vault is not configured")
    return v


# ------------------------------------------------------------------ models

class ProviderOut(BaseModel):
    name: str
    base_url: str
    inject: str
    description: str
    system_credential: bool


class CredentialIn(BaseModel):
    provider: str = Field(min_length=1, max_length=64)
    secret: SecretStr = Field(min_length=8, max_length=4096)
    label: str = Field(default="", max_length=128)
    kind: str = Field(default="api_key", max_length=16)
    base_url: str | None = Field(default=None, max_length=256)
    expires_at: datetime | None = None


class CredentialOut(BaseModel):
    id: int
    provider: str
    label: str
    kind: str
    fingerprint: str
    scopes: list
    system: bool
    created_at: datetime | None
    expires_at: datetime | None
    revoked_at: datetime | None


class ConsentIn(BaseModel):
    provider: str = Field(min_length=1, max_length=64)
    ttl_hours: float = Field(default=24, gt=0, le=MAX_CONSENT_HOURS)
    allow_write: bool = False


class ConsentOut(BaseModel):
    id: int
    provider: str
    credential_id: int | None
    allow_write: bool
    granted_at: datetime | None
    expires_at: datetime
    revoked_at: datetime | None


class ProxyIn(BaseModel):
    grant: str = Field(min_length=8, max_length=256)
    method: str = Field(default="GET", max_length=8)
    path: str = Field(min_length=1, max_length=2048)
    headers: dict[str, str] = Field(default_factory=dict)
    query: dict[str, str] = Field(default_factory=dict)
    body: str | None = Field(default=None, max_length=1_000_000)


class ProxyOut(BaseModel):
    status: int
    body: str
    headers: dict[str, str]
    truncated: bool
    ms: int


# --------------------------------------------------------------- providers

@router.get("/vault/providers", response_model=list[ProviderOut])
async def list_providers(user: dict = Depends(get_current_user)) -> list[ProviderOut]:
    v = _vault()
    specs = v.providers()
    has_sys = await asyncio.to_thread(lambda: {s.name: v.has_system_credential(s.name) for s in specs})
    return [ProviderOut(name=s.name, base_url=s.base_url, inject=s.inject, description=s.description,
                        system_credential=has_sys[s.name]) for s in specs]


# ------------------------------------------------------------- credentials

@router.get("/vault/credentials", response_model=list[CredentialOut])
async def list_credentials(user: dict = Depends(get_current_user)) -> list[CredentialOut]:
    rows = await _vault().list_credentials(user["user_id"])
    return [CredentialOut(**r.public()) for r in rows]


@router.post("/vault/credentials", response_model=CredentialOut, status_code=status.HTTP_201_CREATED)
async def add_credential(req: CredentialIn, user: dict = Depends(get_current_user)) -> CredentialOut:
    try:
        rec = await _vault().add_credential(
            user_id=user["user_id"], provider=req.provider, secret=req.secret.get_secret_value(),
            label=req.label, kind=req.kind, base_url=req.base_url, expires_at=req.expires_at,
        )
    except (VaultError, ValueError) as e:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(e)) from e
    return CredentialOut(**rec.public())


@router.delete("/vault/credentials/{credential_id}")
async def revoke_credential(credential_id: int, user: dict = Depends(get_current_user)) -> dict:
    """404 whether it is missing, already revoked, or someone else's."""
    if not await _vault().revoke_credential(user["user_id"], credential_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "credential not found")
    return {"revoked": credential_id}


# ---------------------------------------------------------------- consents

@router.get("/vault/consents", response_model=list[ConsentOut])
async def list_consents(user: dict = Depends(get_current_user)) -> list[ConsentOut]:
    rows = await _vault().list_consents(user["user_id"])
    return [ConsentOut(**r.public()) for r in rows]


@router.post("/vault/consents", response_model=ConsentOut, status_code=status.HTTP_201_CREATED)
async def grant_consent(req: ConsentIn, user: dict = Depends(get_current_user)) -> ConsentOut:
    try:
        rec = await _vault().grant_consent(user_id=user["user_id"], provider=req.provider,
                                           ttl=timedelta(hours=req.ttl_hours), allow_write=req.allow_write)
    except VaultError as e:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(e)) from e
    return ConsentOut(**rec.public())


@router.delete("/vault/consents/{consent_id}")
async def revoke_consent(consent_id: int, user: dict = Depends(get_current_user)) -> dict:
    if not await _vault().revoke_consent(user["user_id"], consent_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "consent not found")
    return {"revoked": consent_id}


# ------------------------------------------------------------------- audit

@router.get("/vault/audit")
async def vault_audit(limit: int = 50, user: dict = Depends(get_current_user)) -> list[dict]:
    v = _vault()
    if v.audit is None:
        return []
    return await asyncio.to_thread(v.audit.vault_entries, user["user_id"], max(1, min(limit, 200)))


# ------------------------------------------------------------------- proxy

def _proxy_error(e: ProxyError) -> HTTPException:
    return HTTPException(e.status, e.detail)


@router.post("/vault/proxy", response_model=ProxyOut)
async def proxy_json(req: ProxyIn) -> ProxyOut:
    """JSON envelope form: {grant, method, path, headers, query, body}."""
    try:
        r = await _vault().proxy(req.grant, method=req.method, path=req.path, headers=req.headers,
                                 query=req.query, body=req.body)
    except ProxyError as e:
        raise _proxy_error(e) from e
    except VaultUnavailable as e:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(e)) from e
    return ProxyOut(status=r.status, body=r.body, headers=r.headers, truncated=r.truncated, ms=r.ms)


@router.api_route("/vault/proxy/{provider}/{path:path}",
                  methods=["GET", "HEAD", "POST", "PUT", "PATCH", "DELETE"])
async def proxy_passthrough(provider: str, path: str, request: Request) -> Response:
    """Transparent form for stock MCP servers that accept a base-URL override:
    point them at <public_url>/vault/proxy/<provider>/ with the grant as the
    bearer token and they need no code changes. The upstream status and body
    are relayed as-is (after redaction)."""
    auth = request.headers.get("authorization", "")
    token = auth[7:].strip() if auth.lower().startswith("bearer ") else request.headers.get("x-vault-grant", "")
    if not token:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "missing grant")
    v = _vault()
    body = await request.body()
    headers = {k: v_ for k, v_ in request.headers.items()
               if k.lower() in ("content-type", "accept", "user-agent", "x-github-api-version")}
    try:
        r = await v.proxy(token, method=request.method, path="/" + path, headers=headers,
                          query=dict(request.query_params), body=body or None)
    except ProxyError as e:
        raise _proxy_error(e) from e
    except VaultUnavailable as e:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(e)) from e
    if r.truncated:
        r.headers["X-Vault-Truncated"] = "1"
    return Response(content=r.body, status_code=r.status, headers=r.headers,
                    media_type=r.headers.get("content-type", "application/json"))
