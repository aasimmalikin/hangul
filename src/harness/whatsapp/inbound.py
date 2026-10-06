"""Reading Meta's webhook: the signature check and the messages in a delivery.

Every POST carries ``X-Hub-Signature-256: sha256=<hex HMAC-SHA256 of the raw
body, keyed with the app secret>``. A delivery holds message events (what we
act on) and status events (sent / delivered / read, which we ignore).
"""

import hashlib
import hmac
from dataclasses import dataclass


@dataclass
class Inbound:
    wamid: str
    phone: str                      # the sender, digits only (E.164 without "+")
    name: str = ""                  # their WhatsApp profile name
    kind: str = "text"              # text | audio | image | document | choice | unsupported
    text: str = ""                  # the message, a caption, or the tapped button's title
    media_id: str | None = None
    filename: str | None = None
    mime: str | None = None
    reply_id: str | None = None     # the id of a tapped button / list row (approve:…, choice:…)


def signature_ok(raw: bytes, header: str | None, app_secret: str | None) -> bool:
    if not app_secret or not header or not header.startswith("sha256="):
        return False
    expected = hmac.new(app_secret.encode(), raw, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, header.removeprefix("sha256="))


def parse(payload: dict) -> list[Inbound]:
    out: list[Inbound] = []
    for entry in payload.get("entry") or []:
        for change in entry.get("changes") or []:
            value = change.get("value") or {}
            names = {c.get("wa_id"): (c.get("profile") or {}).get("name", "") for c in value.get("contacts") or []}
            for m in value.get("messages") or []:
                phone = "".join(ch for ch in str(m.get("from", "")) if ch.isdigit())
                if not phone or not m.get("id"):
                    continue
                msg = Inbound(wamid=m["id"], phone=phone, name=names.get(m.get("from"), ""))
                kind = m.get("type")
                if kind == "text":
                    msg.text = (m.get("text") or {}).get("body", "")
                elif kind == "interactive":
                    it = m.get("interactive") or {}
                    picked = it.get("button_reply") or it.get("list_reply") or {}
                    msg.kind, msg.reply_id, msg.text = "choice", picked.get("id"), picked.get("title", "")
                elif kind == "button":                      # a template's quick-reply button
                    b = m.get("button") or {}
                    msg.kind, msg.reply_id, msg.text = "choice", b.get("payload"), b.get("text", "")
                elif kind in ("audio", "image", "document"):
                    media = m.get(kind) or {}
                    msg.kind, msg.media_id, msg.mime = kind, media.get("id"), media.get("mime_type")
                    msg.filename, msg.text = media.get("filename"), media.get("caption", "")
                else:
                    msg.kind = "unsupported"
                out.append(msg)
    return out
