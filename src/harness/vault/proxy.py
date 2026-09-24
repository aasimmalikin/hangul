"""The one place a real credential is decrypted: validate the grant, apply
policy, inject the secret, forward, and give back a redacted response.

The caller (agent tool, MCP server, /vault/proxy route) only ever sees the
grant token going in and a scrubbed body coming out."""

import base64
import time
from dataclasses import dataclass, field

import httpx

from harness.logging import log
from harness.vault.crypto import Cipher
from harness.vault.grants import Grant, GrantError, GrantStore
from harness.vault.policy import VaultPolicy
from harness.vault.providers import ProviderSpec
from harness.vault.redact import Redactor
from harness.vault.store import CredentialRecord

# headers a caller must never be able to set (they would override or leak the injected credential)
STRIP_REQUEST_HEADERS = {"authorization", "cookie", "x-api-key", "proxy-authorization", "host",
                         "content-length", "transfer-encoding"}
# response headers that would carry upstream session state to the caller
STRIP_RESPONSE_HEADERS = {"set-cookie", "www-authenticate", "proxy-authenticate"}
PASS_RESPONSE_HEADERS = {"content-type", "x-ratelimit-remaining", "x-ratelimit-limit", "retry-after",
                         "link", "etag", "last-modified"}


class ProxyError(Exception):
    def __init__(self, status: int, detail: str) -> None:
        super().__init__(detail)
        self.status = status
        self.detail = detail


@dataclass
class ProxyResponse:
    status: int
    body: str
    headers: dict[str, str] = field(default_factory=dict)
    truncated: bool = False
    ms: int = 0


def inject(spec: ProviderSpec, secret: str, headers: dict[str, str], params: dict[str, str]) -> None:
    if spec.inject == "bearer":
        headers["Authorization"] = f"Bearer {secret}"
    elif spec.inject == "header":
        headers[spec.inject_name] = secret
    elif spec.inject == "query":
        params[spec.inject_name] = secret
    elif spec.inject == "basic":
        headers["Authorization"] = "Basic " + base64.b64encode(secret.encode()).decode()
    else:
        raise ProxyError(500, f"unknown inject kind {spec.inject!r}")


async def proxy_request(
    *,
    grant: Grant,
    credential: CredentialRecord,
    spec: ProviderSpec,
    cipher: Cipher,
    grants: GrantStore,
    policy: VaultPolicy,
    redactor: Redactor,
    http: httpx.AsyncClient,
    method: str,
    path: str,
    headers: dict[str, str] | None = None,
    query: dict[str, str] | None = None,
    body: bytes | str | None = None,
    max_body_bytes: int = 1_000_000,
    audit=None,
) -> ProxyResponse:
    method = method.upper()
    raw_body = body.encode() if isinstance(body, str) else (body or b"")
    verdict = policy.check(grant.scope, spec, method, path, len(raw_body), grant.calls_left)
    if not verdict.allowed:
        _audit(audit, grant, spec, method, path, status=403, ms=0, denied=verdict.reason)
        raise ProxyError(403, verdict.reason)
    if not credential.usable:
        raise ProxyError(403, "credential revoked or expired")

    try:
        await grants.consume(grant)
    except GrantError as e:
        raise ProxyError(403, str(e)) from e

    out_headers = {k: v for k, v in (headers or {}).items() if k.lower() not in STRIP_REQUEST_HEADERS}
    out_headers.setdefault("Accept", "application/json")
    if raw_body and "content-type" not in {k.lower() for k in out_headers}:
        out_headers["Content-Type"] = "application/json"
    params = dict(query or {})

    # the only decrypt in the codebase; the plaintext lives in this frame only
    secret = cipher.decrypt(credential.ciphertext)
    redactor.register(secret, spec.name)
    inject(spec, secret, out_headers, params)

    url = spec.base_url.rstrip("/") + path
    started = time.perf_counter()
    try:
        resp = await http.request(method, url, headers=out_headers, params=params, content=raw_body or None)
    except httpx.HTTPError as e:
        ms = int((time.perf_counter() - started) * 1000)
        _audit(audit, grant, spec, method, path, status=502, ms=ms, denied=f"upstream {type(e).__name__}")
        raise ProxyError(502, f"upstream request failed ({type(e).__name__})") from e
    finally:
        del secret
    ms = int((time.perf_counter() - started) * 1000)

    content = resp.content
    truncated = len(content) > max_body_bytes
    text = content[:max_body_bytes].decode(resp.encoding or "utf-8", errors="replace")
    text = redactor.scrub_text(text)
    keep = {k: v for k, v in resp.headers.items()
            if k.lower() in PASS_RESPONSE_HEADERS and k.lower() not in STRIP_RESPONSE_HEADERS}
    _audit(audit, grant, spec, method, path, status=resp.status_code, ms=ms)
    return ProxyResponse(status=resp.status_code, body=text, headers=keep, truncated=truncated, ms=ms)


def _audit(audit, grant: Grant, spec: ProviderSpec, method: str, path: str, *, status: int, ms: int,
           denied: str | None = None) -> None:
    entry = {"subject": grant.scope.subject, "thread_id": grant.scope.thread_id, "provider": spec.name,
             "method": method, "path": path, "status": status, "ms": ms}
    if denied:
        entry["denied"] = denied
    log.info("vault proxy", **entry)
    if audit is not None:
        audit.record_vault(**entry)
