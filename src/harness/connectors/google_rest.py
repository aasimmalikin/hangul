"""The Google Workspace connector over Google's REST APIs.

Google's own Workspace MCP servers need a Workspace organisation enrolled in
the Developer Preview; the REST APIs (Gmail, Calendar, Drive, Docs) work for
any account that granted the scopes. Same switch in the UI, same tool
namespaces (``gmail__*`` ...) so the policy tiers and the eval concerns apply
unchanged. Tools are built per user: each call fetches that user's access
token from ``GoogleTokenSource`` (refreshed and cached there) and never
exposes it to the model."""

import base64
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from email.message import EmailMessage

import httpx

from harness.integrations.google_oauth import GoogleNotConnected, google_tokens
from harness.logging import log
from harness.tools.base import Tool, ToolOutput

GMAIL = "https://gmail.googleapis.com/gmail/v1/users/me"
CALENDAR = "https://www.googleapis.com/calendar/v3"
DRIVE = "https://www.googleapis.com/drive/v3"
DOCS = "https://docs.googleapis.com/v1"
MAX_TEXT = 12_000


class GoogleApiError(Exception):
    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.message = message


async def _request(http: httpx.AsyncClient | None, user_id: str, product: str, method: str, url: str, *,
                   params: dict | None = None, json_body: dict | None = None, retry: bool = True) -> httpx.Response:
    """One authenticated call. A 401 is retried once with a fresh token."""
    src = google_tokens()
    token = await src.access_token(user_id, product=product)
    client = http or httpx.AsyncClient(timeout=20.0)
    try:
        r = await client.request(method, url, params=params, json=json_body,
                                 headers={"Authorization": f"Bearer {token}", "Accept": "application/json"})
    finally:
        if http is None:
            await client.aclose()
    if r.status_code == 401 and retry:
        src.forget(user_id)
        return await _request(http, user_id, product, method, url, params=params, json_body=json_body, retry=False)
    if r.status_code >= 400:
        try:
            msg = r.json().get("error", {}).get("message") or r.text[:300]
        except ValueError:
            msg = r.text[:300]
        raise GoogleApiError(r.status_code, msg)
    return r


def _handler(product: str, fn: Callable[..., Awaitable[str | ToolOutput]]) -> Callable[..., Awaitable[str | ToolOutput]]:
    """Wrap a tool body so every failure comes back as text the model can act on."""
    async def run(**kw) -> str | ToolOutput:
        try:
            return await fn(**kw)
        except GoogleNotConnected as e:
            return f"GOOGLE_NOT_CONNECTED: {e}. Ask the user to connect Google Workspace at /vault."
        except GoogleApiError as e:
            if e.status == 403 and "insufficient" in e.message.lower():
                return f"GOOGLE_SCOPE_MISSING: {e.message}. Ask the user to reconnect Google Workspace and grant {product} access."
            return f"GOOGLE_API_ERROR ({e.status}): {e.message}"
        except httpx.HTTPError as e:
            log.warning("google api unreachable", product=product, error=str(e))
            return f"GOOGLE_UNAVAILABLE: Google {product} could not be reached ({type(e).__name__}). Do not retry now."
    return run


# ------------------------------------------------------------------ gmail

def _header(msg: dict, name: str) -> str:
    for h in msg.get("payload", {}).get("headers", []):
        if h.get("name", "").lower() == name.lower():
            return h.get("value", "")
    return ""


def _decode(data: str) -> str:
    try:
        return base64.urlsafe_b64decode(data + "=" * (-len(data) % 4)).decode("utf-8", errors="replace")
    except (ValueError, TypeError):
        return ""


def _body_text(payload: dict) -> str:
    """Prefer text/plain parts; fall back to stripping tags from text/html."""
    plain, html = [], []

    def walk(part: dict) -> None:
        mime = part.get("mimeType", "")
        data = part.get("body", {}).get("data")
        if data and mime == "text/plain":
            plain.append(_decode(data))
        elif data and mime == "text/html":
            html.append(_decode(data))
        for p in part.get("parts", []) or []:
            walk(p)
    walk(payload)
    if plain:
        return "\n".join(plain)
    if html:
        import re
        text = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", "\n".join(html), flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r"<br\s*/?>|</p>|</div>", "\n", text, flags=re.IGNORECASE)
        text = re.sub(r"<[^>]+>", " ", text)
        return re.sub(r"[ \t]+", " ", text).strip()
    return ""


def _ui_message(m: dict, *, body: bool = False) -> dict:
    d = {"id": m.get("id"), "thread_id": m.get("threadId"), "from": _header(m, "From"), "to": _header(m, "To"),
         "subject": _header(m, "Subject"), "date": _header(m, "Date"), "snippet": m.get("snippet", ""),
         "labels": m.get("labelIds", []), "unread": "UNREAD" in m.get("labelIds", [])}
    if body:
        text = _body_text(m.get("payload", {}))
        d["body"] = text[:MAX_TEXT]
    return d


def _format_message(m: dict, *, body: bool = False) -> str:
    line = (f"[{m.get('id')}] thread={m.get('threadId')} · {_header(m, 'Date')}\n"
            f"  From: {_header(m, 'From')}\n  To: {_header(m, 'To')}\n  Subject: {_header(m, 'Subject')}\n"
            f"  Labels: {', '.join(m.get('labelIds', []))}\n")
    if body:
        text = _body_text(m.get("payload", {}))
        line += "  ---\n" + (text[:MAX_TEXT] + ("…" if len(text) > MAX_TEXT else "")) + "\n"
    else:
        line += f"  {m.get('snippet', '')}\n"
    return line


def make_google_tools(user_id: str, http: httpx.AsyncClient | None = None) -> list[Tool]:
    async def call(product: str, method: str, url: str, **kw) -> httpx.Response:
        return await _request(http, user_id, product, method, url, **kw)

    # -------------------------------------------------------------- gmail
    async def gmail_search(query: str = "", max_results: int = 10, label: str | None = None) -> str:
        q = (query or "").strip()
        params = {"maxResults": max(1, min(int(max_results or 10), 25))}
        if q:
            params["q"] = q
        if label:
            params["labelIds"] = label
        r = await call("gmail", "GET", f"{GMAIL}/messages", params=params)
        ids = [m["id"] for m in r.json().get("messages", [])]
        if not ids:
            return "No messages match."
        out, ui = [], []
        for mid in ids:
            m = (await call("gmail", "GET", f"{GMAIL}/messages/{mid}",
                            params={"format": "metadata", "metadataHeaders": ["From", "To", "Subject", "Date"]})).json()
            out.append(_format_message(m))
            ui.append(_ui_message(m))
        return ToolOutput(f"{len(out)} message(s) for query {q!r}:\n\n" + "\n".join(out),
                          ui={"kind": "gmail_messages", "query": q, "messages": ui})

    async def gmail_get_thread(thread_id: str) -> str:
        r = await call("gmail", "GET", f"{GMAIL}/threads/{thread_id}", params={"format": "full"})
        msgs = r.json().get("messages", [])
        if not msgs:
            return f"Thread {thread_id} has no messages."
        parts = [_format_message(m, body=True) for m in msgs]
        text = "\n".join(parts)
        return ToolOutput(text[:MAX_TEXT * 2] + ("…" if len(text) > MAX_TEXT * 2 else ""),
                          ui={"kind": "gmail_thread", "thread_id": thread_id,
                              "subject": _header(msgs[0], "Subject"), "messages": [_ui_message(m, body=True) for m in msgs]})

    async def gmail_get_message(message_id: str) -> str:
        m = (await call("gmail", "GET", f"{GMAIL}/messages/{message_id}", params={"format": "full"})).json()
        return ToolOutput(_format_message(m, body=True),
                          ui={"kind": "gmail_thread", "thread_id": m.get("threadId"), "subject": _header(m, "Subject"),
                              "messages": [_ui_message(m, body=True)]})

    def _mime(to: str, subject: str, body: str, cc: str | None, thread_id: str | None) -> dict:
        msg = EmailMessage()
        msg["To"] = to
        msg["Subject"] = subject
        if cc:
            msg["Cc"] = cc
        msg.set_content(body)
        message: dict = {"raw": base64.urlsafe_b64encode(msg.as_bytes()).decode()}
        if thread_id:
            message["threadId"] = thread_id
        return message

    async def gmail_create_draft(to: str, subject: str, body: str, cc: str | None = None,
                                 thread_id: str | None = None) -> ToolOutput:
        r = await call("gmail", "POST", f"{GMAIL}/drafts", json_body={"message": _mime(to, subject, body, cc, thread_id)})
        d = r.json()
        return ToolOutput(f"Draft created (id {d.get('id')}) to {to}: {subject!r}. It is in the user's Drafts folder, not sent. "
                          f"To send it, call gmail__send_draft with draft_id={d.get('id')}.",
                          ui={"kind": "gmail_draft", "draft_id": d.get("id"), "to": to, "cc": cc, "subject": subject, "body": body})

    async def gmail_send_message(to: str, subject: str, body: str, cc: str | None = None,
                                 thread_id: str | None = None) -> ToolOutput:
        r = await call("gmail", "POST", f"{GMAIL}/messages/send", json_body=_mime(to, subject, body, cc, thread_id))
        m = r.json()
        return ToolOutput(f"Email sent to {to}: {subject!r} (message id {m.get('id')}).",
                          ui={"kind": "gmail_sent", "message_id": m.get("id"), "to": to, "cc": cc, "subject": subject, "body": body})

    async def gmail_send_draft(draft_id: str) -> ToolOutput:
        r = await call("gmail", "POST", f"{GMAIL}/drafts/send", json_body={"id": draft_id})
        m = r.json()
        return ToolOutput(f"Draft {draft_id} sent (message id {m.get('id')}).",
                          ui={"kind": "gmail_sent", "message_id": m.get("id"), "draft_id": draft_id})

    # ----------------------------------------------------------- calendar
    async def calendar_list_events(time_min: str | None = None, time_max: str | None = None,
                                   max_results: int = 10, calendar_id: str = "primary", query: str | None = None) -> str:
        now = datetime.now(UTC)
        params = {
            "timeMin": time_min or now.isoformat(),
            "timeMax": time_max or (now + timedelta(days=7)).isoformat(),
            "maxResults": max(1, min(int(max_results or 10), 50)),
            "singleEvents": "true", "orderBy": "startTime",
        }
        if query:
            params["q"] = query
        r = await call("calendar", "GET", f"{CALENDAR}/calendars/{calendar_id}/events", params=params)
        items = r.json().get("items", [])
        if not items:
            return f"No events between {params['timeMin']} and {params['timeMax']}."
        lines, ui = [], []
        for e in items:
            start = e.get("start", {}).get("dateTime") or e.get("start", {}).get("date", "")
            end = e.get("end", {}).get("dateTime") or e.get("end", {}).get("date", "")
            who = ", ".join(a.get("email", "") for a in e.get("attendees", [])[:6])
            lines.append(f"[{e.get('id')}] {start} → {end}\n  {e.get('summary', '(no title)')}"
                         + (f"\n  where: {e['location']}" if e.get("location") else "")
                         + (f"\n  with: {who}" if who else "")
                         + (f"\n  {e['description'][:300]}" if e.get("description") else ""))
            ui.append({"id": e.get("id"), "summary": e.get("summary", "(no title)"), "start": start, "end": end,
                       "all_day": "date" in e.get("start", {}), "location": e.get("location"),
                       "attendees": [a.get("email", "") for a in e.get("attendees", [])[:6]],
                       "link": e.get("htmlLink"), "description": (e.get("description") or "")[:300]})
        return ToolOutput(f"{len(lines)} event(s):\n\n" + "\n".join(lines),
                          ui={"kind": "calendar_events", "time_min": params["timeMin"], "time_max": params["timeMax"], "events": ui})

    async def calendar_create_event(summary: str, start: str, end: str, description: str | None = None,
                                    attendees: list[str] | None = None, location: str | None = None,
                                    calendar_id: str = "primary", timezone: str | None = None) -> str:
        def when(v: str) -> dict:
            if len(v) == 10:
                return {"date": v}
            d = {"dateTime": v}
            if timezone:
                d["timeZone"] = timezone
            return d
        body: dict = {"summary": summary, "start": when(start), "end": when(end)}
        if description:
            body["description"] = description
        if location:
            body["location"] = location
        if attendees:
            body["attendees"] = [{"email": a} for a in attendees]
        r = await call("calendar", "POST", f"{CALENDAR}/calendars/{calendar_id}/events", json_body=body)
        e = r.json()
        return ToolOutput(f"Event created: {e.get('summary')} ({e.get('htmlLink', e.get('id'))})",
                          ui={"kind": "calendar_events", "created": True,
                              "events": [{"id": e.get("id"), "summary": e.get("summary"), "start": start, "end": end,
                                          "all_day": len(start) == 10, "location": location, "attendees": attendees or [],
                                          "link": e.get("htmlLink"), "description": (description or "")[:300]}]})

    # -------------------------------------------------------------- drive
    async def drive_search_files(query: str = "", max_results: int = 10) -> str:
        q = query.strip()
        if q and not any(op in q for op in (" contains ", "=", "mimeType", "'")):
            q = f"name contains '{q}' or fullText contains '{q}'"
        params = {"pageSize": max(1, min(int(max_results or 10), 50)), "orderBy": "modifiedTime desc",
                  "fields": "files(id,name,mimeType,modifiedTime,size,webViewLink,owners(emailAddress))"}
        if q:
            params["q"] = q
        r = await call("drive", "GET", f"{DRIVE}/files", params=params)
        files = r.json().get("files", [])
        if not files:
            return "No files match."
        return ToolOutput(f"{len(files)} file(s):\n\n" + "\n".join(
            f"[{f['id']}] {f['name']}\n  {f.get('mimeType')} · modified {f.get('modifiedTime')}"
            + (f" · {f['size']} bytes" if f.get("size") else "") + f"\n  {f.get('webViewLink', '')}" for f in files),
            ui={"kind": "drive_files", "files": [{"id": f["id"], "name": f["name"], "mime": f.get("mimeType"),
                                                 "modified": f.get("modifiedTime"), "size": f.get("size"),
                                                 "link": f.get("webViewLink")} for f in files]})

    async def drive_get_file(file_id: str, max_chars: int = MAX_TEXT) -> str:
        meta = (await call("drive", "GET", f"{DRIVE}/files/{file_id}",
                           params={"fields": "id,name,mimeType,size,modifiedTime,webViewLink"})).json()
        mime = meta.get("mimeType", "")
        head = f"[{meta['id']}] {meta.get('name')} · {mime} · modified {meta.get('modifiedTime')}\n{meta.get('webViewLink', '')}\n---\n"
        limit = max(500, min(int(max_chars or MAX_TEXT), MAX_TEXT * 4))
        export = {"application/vnd.google-apps.document": "text/plain",
                  "application/vnd.google-apps.spreadsheet": "text/csv",
                  "application/vnd.google-apps.presentation": "text/plain"}.get(mime)
        if export:
            r = await call("drive", "GET", f"{DRIVE}/files/{file_id}/export", params={"mimeType": export})
            text = r.text
        elif mime.startswith("text/") or mime in ("application/json", "application/xml"):
            r = await call("drive", "GET", f"{DRIVE}/files/{file_id}", params={"alt": "media"})
            text = r.text
        else:
            return head + "(binary file; contents not shown)"
        return head + text[:limit] + ("…" if len(text) > limit else "")

    # --------------------------------------------------------------- docs
    def _doc_text(doc: dict) -> str:
        out = []
        for el in doc.get("body", {}).get("content", []):
            para = el.get("paragraph")
            if not para:
                continue
            out.append("".join(r.get("textRun", {}).get("content", "") for r in para.get("elements", [])))
        return "".join(out)

    async def docs_get_document(document_id: str, max_chars: int = MAX_TEXT) -> str:
        doc = (await call("docs", "GET", f"{DOCS}/documents/{document_id}")).json()
        text = _doc_text(doc)
        limit = max(500, min(int(max_chars or MAX_TEXT), MAX_TEXT * 4))
        return ToolOutput(f"# {doc.get('title')}\n\n" + text[:limit] + ("…" if len(text) > limit else ""),
                          ui={"kind": "docs_document", "id": document_id, "title": doc.get("title"), "text": text[:limit]})

    async def docs_append_text(document_id: str, text: str) -> str:
        doc = (await call("docs", "GET", f"{DOCS}/documents/{document_id}", params={"fields": "body(content(endIndex))"})).json()
        end = max((el.get("endIndex", 1) for el in doc.get("body", {}).get("content", [])), default=1)
        body = {"requests": [{"insertText": {"location": {"index": max(1, end - 1)}, "text": text}}]}
        await call("docs", "POST", f"{DOCS}/documents/{document_id}:batchUpdate", json_body=body)
        return f"Appended {len(text)} characters to document {document_id}."

    obj = {"type": "object"}
    return [
        Tool(name="gmail__search_messages",
             description="Search the user's Gmail. `query` uses Gmail search syntax (e.g. 'newer_than:1d', "
                         "'from:alice is:unread', 'subject:invoice'). Returns sender, subject, date, labels and a snippet; "
                         "use gmail__get_thread for full text.",
             parameter={**obj, "properties": {"query": {"type": "string"}, "max_results": {"type": "integer", "minimum": 1, "maximum": 25},
                                              "label": {"type": "string", "description": "e.g. INBOX, UNREAD, STARRED"}}},
             handler=_handler("gmail", gmail_search)),
        Tool(name="gmail__get_thread", description="Full text of a Gmail thread (all messages) by thread id.",
             parameter={**obj, "properties": {"thread_id": {"type": "string"}}, "required": ["thread_id"]},
             handler=_handler("gmail", gmail_get_thread)),
        Tool(name="gmail__get_message", description="Full text of one Gmail message by message id.",
             parameter={**obj, "properties": {"message_id": {"type": "string"}}, "required": ["message_id"]},
             handler=_handler("gmail", gmail_get_message)),
        Tool(name="gmail__create_draft",
             description="Create a DRAFT email in the user's Gmail (never sends). Use when the user asks you to write or reply to an email.",
             parameter={**obj, "properties": {"to": {"type": "string"}, "subject": {"type": "string"}, "body": {"type": "string"},
                                              "cc": {"type": "string"}, "thread_id": {"type": "string", "description": "reply in this thread"}},
                        "required": ["to", "subject", "body"]},
             handler=_handler("gmail", gmail_create_draft)),
        Tool(name="gmail__send_message",
             description="SEND an email from the user's Gmail. Only when the user explicitly asked to send. Requires the user's approval.",
             parameter={**obj, "properties": {"to": {"type": "string"}, "subject": {"type": "string"}, "body": {"type": "string"},
                                              "cc": {"type": "string"}, "thread_id": {"type": "string", "description": "reply in this thread"}},
                        "required": ["to", "subject", "body"]},
             handler=_handler("gmail", gmail_send_message)),
        Tool(name="gmail__send_draft", description="Send an existing Gmail draft by draft id. Requires the user's approval.",
             parameter={**obj, "properties": {"draft_id": {"type": "string"}}, "required": ["draft_id"]},
             handler=_handler("gmail", gmail_send_draft)),
        Tool(name="calendar__list_events",
             description="Events on the user's Google Calendar. Defaults to the next 7 days; pass RFC3339 time_min/time_max for another range.",
             parameter={**obj, "properties": {"time_min": {"type": "string"}, "time_max": {"type": "string"}, "max_results": {"type": "integer"},
                                              "calendar_id": {"type": "string"}, "query": {"type": "string"}}},
             handler=_handler("calendar", calendar_list_events)),
        Tool(name="calendar__create_event",
             description="Create a calendar event. start/end are RFC3339 date-times (or YYYY-MM-DD for all-day). Requires the user's approval.",
             parameter={**obj, "properties": {"summary": {"type": "string"}, "start": {"type": "string"}, "end": {"type": "string"},
                                              "description": {"type": "string"}, "attendees": {"type": "array", "items": {"type": "string"}},
                                              "location": {"type": "string"}, "calendar_id": {"type": "string"}, "timezone": {"type": "string"}},
                        "required": ["summary", "start", "end"]},
             handler=_handler("calendar", calendar_create_event)),
        Tool(name="drive__search_files",
             description="Find files in the user's Google Drive by name/content (plain words) or a Drive query (e.g. \"mimeType='application/pdf'\").",
             parameter={**obj, "properties": {"query": {"type": "string"}, "max_results": {"type": "integer"}}},
             handler=_handler("drive", drive_search_files)),
        Tool(name="drive__get_file", description="Read a Drive file's text (Docs/Sheets/Slides are exported as text; binaries show metadata only).",
             parameter={**obj, "properties": {"file_id": {"type": "string"}, "max_chars": {"type": "integer"}}, "required": ["file_id"]},
             handler=_handler("drive", drive_get_file)),
        Tool(name="docs__get_document", description="Read a Google Doc's text by document id.",
             parameter={**obj, "properties": {"document_id": {"type": "string"}, "max_chars": {"type": "integer"}}, "required": ["document_id"]},
             handler=_handler("docs", docs_get_document)),
        Tool(name="docs__append_text", description="Append text to the end of a Google Doc. Requires the user's approval.",
             parameter={**obj, "properties": {"document_id": {"type": "string"}, "text": {"type": "string"}}, "required": ["document_id", "text"]},
             handler=_handler("docs", docs_append_text)),
    ]


