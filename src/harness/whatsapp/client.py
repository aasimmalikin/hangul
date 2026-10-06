"""Calls to Meta's WhatsApp Cloud API, every one through the vault (provider
``whatsapp``; media bytes from ``whatsapp_media``), so the token never leaves
the proxy. Errors come back as WhatsAppError; callers log and carry on."""

import json
from urllib.parse import parse_qsl, urlsplit

from harness.config import get_settings
from harness.logging import log
from harness.vault import current as current_vault
from harness.vault.vault import SYSTEM
from harness.whatsapp.fmt import one_line

BUTTON_TITLE = 20          # Meta's limits for interactive messages
ROW_TITLE = 24
ROW_DESCRIPTION = 72
BODY = 1024


class WhatsAppError(RuntimeError):
    pass


def _cut(text: str, n: int) -> str:
    text = (text or "").strip()
    return text if len(text) <= n else text[: n - 1].rstrip() + "…"


async def _graph(method: str, path: str, body: dict | None = None, *, want_bytes: bool = False):
    v = current_vault()
    if v is None:
        raise WhatsAppError("the vault is not running")
    s = get_settings()
    try:
        r = await v.call(subject=SYSTEM, provider="whatsapp", method=method,
                         path=f"/{s.whatsapp_api_version}/{path.lstrip('/')}",
                         body=json.dumps(body) if body is not None else None, want_bytes=want_bytes)
    except Exception as e:  # noqa: BLE001 - vault/proxy errors
        raise WhatsAppError(f"{type(e).__name__}: {e}") from e
    if r.status >= 400:
        raise WhatsAppError(f"Meta answered {r.status}: {r.body[:300]}")
    return r


async def _send(payload: dict) -> str | None:
    """POST one message; returns its wamid."""
    s = get_settings()
    r = await _graph("POST", f"{s.whatsapp_phone_number_id}/messages", {"messaging_product": "whatsapp", **payload})
    try:
        return (json.loads(r.body).get("messages") or [{}])[0].get("id")
    except ValueError:
        return None


async def send_text(to: str, text: str) -> str | None:
    return await _send({"to": to, "type": "text", "text": {"body": text[:4096], "preview_url": True}})


async def send_buttons(to: str, body: str, buttons: list[tuple[str, str]]) -> str | None:
    """Up to 3 reply buttons: (id, title)."""
    return await _send({"to": to, "type": "interactive", "interactive": {
        "type": "button", "body": {"text": _cut(body, BODY)},
        "action": {"buttons": [{"type": "reply", "reply": {"id": bid[:256], "title": _cut(title, BUTTON_TITLE)}}
                               for bid, title in buttons[:3]]}}})


async def send_list(to: str, body: str, button: str, rows: list[tuple[str, str, str]]) -> str | None:
    """A menu of up to 10 rows: (id, title, description)."""
    return await _send({"to": to, "type": "interactive", "interactive": {
        "type": "list", "body": {"text": _cut(body, BODY)},
        "action": {"button": _cut(button, BUTTON_TITLE), "sections": [{"title": "Options", "rows": [
            {"id": rid[:200], "title": _cut(title, ROW_TITLE), "description": _cut(desc, ROW_DESCRIPTION)}
            for rid, title, desc in rows[:10]]}]}}})


async def send_template(to: str, name: str, params: list[str], buttons: list[str] | None = None) -> str | None:
    """An approved template (needed outside the 24-hour window). ``buttons`` are the
    payloads of its quick-reply buttons, in order (a tap comes back as that payload)."""
    s = get_settings()
    components = [{"type": "body", "parameters": [{"type": "text", "text": one_line(p, 900)} for p in params]}] if params else []
    components += [{"type": "button", "sub_type": "quick_reply", "index": str(i),
                    "parameters": [{"type": "payload", "payload": payload}]} for i, payload in enumerate(buttons or [])]
    return await _send({"to": to, "type": "template", "template": {
        "name": name, "language": {"code": s.whatsapp_template_language}, "components": components}})


async def mark_read(wamid: str, typing: bool = True) -> None:
    """Blue ticks, plus the "typing…" indicator while Hangul works (best effort)."""
    s = get_settings()
    body: dict = {"messaging_product": "whatsapp", "status": "read", "message_id": wamid}
    if typing:
        body["typing_indicator"] = {"type": "text"}
    try:
        await _graph("POST", f"{s.whatsapp_phone_number_id}/messages", body)
    except WhatsAppError as e:
        log.info("whatsapp mark_read failed", error=str(e)[:200])


async def download_media(media_id: str) -> tuple[bytes, str]:
    """A received voice note / photo / document: (bytes, mime type)."""
    meta = json.loads((await _graph("GET", media_id)).body)
    url, mime = meta.get("url"), meta.get("mime_type", "application/octet-stream")
    if not url:
        raise WhatsAppError("media has no download url")
    parts = urlsplit(url)
    v = current_vault()
    r = await v.call(subject=SYSTEM, provider="whatsapp_media", method="GET", path=parts.path,
                     query=dict(parse_qsl(parts.query)), want_bytes=True)
    if r.status >= 400 or not r.raw:
        raise WhatsAppError(f"media download failed ({r.status})")
    return r.raw, mime
