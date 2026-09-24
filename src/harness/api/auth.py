import ipaddress
import time

import jwt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from harness.auth.revocation import is_revoked
from harness.config import get_settings
from harness.logging import log

_bearer = HTTPBearer(auto_error = True)

async def get_current_user(creds: HTTPAuthorizationCredentials = Depends(_bearer))->dict:
    setting = get_settings()
    try:
        payload = jwt.decode(
            creds.credentials,
            setting.jwt_secret,
            algorithms = [setting.jwt_algorithm],
        )

    except jwt.ExpiredSignatureError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "token expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid token")

    jti = payload.get("jti")
    if jti and await is_revoked(jti):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "token revoked")

    user_id = payload.get("sub")

    if not user_id:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "token missing subject")
    return {
        "user_id": user_id,
        "role": payload.get("role", "user"),
        # identity claims the BFF copies from the Google session; only admin routes read them
        "email": (payload.get("email") or "").strip().lower() or None,
        "auth_provider": payload.get("auth_provider"),
        "auth_at": payload.get("auth_at"),
    }


def admin_emails() -> set[str]:
    return {e.strip().lower() for e in get_settings().admin_emails.split(",") if e.strip()}


def _client_ip(request: Request) -> str | None:
    # request.client is the direct peer. X-Forwarded-For is deliberately NOT
    # trusted here: behind a proxy, terminate the allowlist at the proxy.
    return request.client.host if request.client else None


def _ip_allowed(ip: str | None) -> bool:
    raw = get_settings().admin_ip_allowlist
    if not raw.strip():
        return True
    if ip is None:
        return False
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return False
    for cidr in raw.split(","):
        cidr = cidr.strip()
        if not cidr:
            continue
        try:
            if addr in ipaddress.ip_network(cidr, strict=False):
                return True
        except ValueError:
            continue
    return False


def require_admin(request: Request, user: dict = Depends(get_current_user))->dict:
    """Admin = an allowlisted email, signed in through Google recently, from an
    allowed network. The role claim is not enough on its own: the allowlist is
    the source of truth and it lives only on this side."""
    settings = get_settings()
    email = user.get("email")
    ip = _client_ip(request)
    reason = None
    if not email or email not in admin_emails():
        reason = "email not authorised"
    elif user.get("auth_provider") != "google":
        reason = "google sign-in required"
    elif not isinstance(user.get("auth_at"), (int, float)) or \
            time.time() - float(user["auth_at"]) > settings.admin_max_auth_age_s:
        reason = "sign-in too old, re-authenticate"
    elif not _ip_allowed(ip):
        reason = "client network not allowed"
    if reason:
        log.warning("admin denied", email=email, user_id=user["user_id"], ip=ip, path=request.url.path, reason=reason)
        code = status.HTTP_401_UNAUTHORIZED if reason.startswith("sign-in too old") else status.HTTP_403_FORBIDDEN
        raise HTTPException(code, reason)
    log.info("admin request", email=email, user_id=user["user_id"], ip=ip,
             method=request.method, path=request.url.path)
    return {**user, "ip": ip}
