"""The Google Workspace connector over Google's REST APIs.

Google's own Workspace MCP servers need a Workspace organisation enrolled in
the Developer Preview; the REST APIs (Gmail, Calendar, Drive, Docs, Sheets,
Contacts) work for
any account that granted the scopes. Same switch in the UI, same tool
namespaces (``gmail__*`` ...) so the policy tiers and the eval concerns apply
unchanged. Tools are built per user: each call fetches that user's access
token from ``GoogleTokenSource`` (refreshed and cached there) and never
exposes it to the model."""

import base64
from collections.abc import Awaitable, Callable
from datetime import UTC, date, datetime, timedelta
from email.message import EmailMessage

import httpx

from harness.integrations.google_oauth import GoogleNotConnected, google_tokens
from harness.logging import log
from harness.tools.base import Tool, ToolOutput

GMAIL = "https://gmail.googleapis.com/gmail/v1/users/me"
CALENDAR = "https://www.googleapis.com/calendar/v3"
DRIVE = "https://www.googleapis.com/drive/v3"
DOCS = "https://docs.googleapis.com/v1"
SHEETS = "https://sheets.googleapis.com/v4/spreadsheets"
PEOPLE = "https://people.googleapis.com/v1"
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


def free_slots(start: datetime, end: datetime, busy: list[tuple[datetime, datetime]], minutes: int,
               day_start: str, day_end: str, tz) -> list[tuple[datetime, datetime]]:
    """Gaps of at least ``minutes`` between busy blocks, inside the working
    hours of each day (in ``tz``), within [start, end)."""
    out: list[tuple[datetime, datetime]] = []
    need = timedelta(minutes=max(5, minutes))
    hs, ms = (int(x) for x in day_start.split(":"))
    he, me = (int(x) for x in day_end.split(":"))
    blocks = sorted((a.astimezone(tz), b.astimezone(tz)) for a, b in busy)
    day = start.astimezone(tz).replace(hour=0, minute=0, second=0, microsecond=0)
    while day < end.astimezone(tz):
        lo = max(day.replace(hour=hs, minute=ms), start.astimezone(tz))
        hi = min(day.replace(hour=he, minute=me), end.astimezone(tz))
        cur = lo
        for a, b in blocks:
            if b <= cur or a >= hi:
                continue
            if a - cur >= need:
                out.append((cur, a))
            cur = max(cur, b)
        if hi - cur >= need:
            out.append((cur, hi))
        day += timedelta(days=1)
    return out


def upcoming(people: list[dict], today: date, days: int = 7) -> list[dict]:
    """Birthdays from People API ``connections`` falling within ``days`` of
    ``today`` (inclusive), soonest first. A 29 February birthday is shown on
    the 28th in other years; the year, when Google has it, gives the age."""
    out = []
    for p in people:
        name = ((p.get("names") or [{}])[0].get("displayName") or "").strip()
        bday = next((b.get("date") for b in p.get("birthdays", []) if (b.get("date") or {}).get("month")), None)
        if not name or not bday or not bday.get("day"):
            continue
        month, day = int(bday["month"]), int(bday["day"])
        for year in (today.year, today.year + 1):
            try:
                when = date(year, month, day)
            except ValueError:               # 29 Feb in a non-leap year
                when = date(year, 2, 28)
            if when >= today:
                break
        in_days = (when - today).days
        if in_days <= days:
            item = {"name": name, "date": when.isoformat(), "in_days": in_days}
            if bday.get("year"):
                item["turns"] = when.year - int(bday["year"])
            out.append(item)
    return sorted(out, key=lambda b: (b["in_days"], b["name"]))


async def upcoming_birthdays(user_id: str, today: date, days: int = 7,
                             http: httpx.AsyncClient | None = None) -> list[dict]:
    """The user's saved contacts with a birthday in the next ``days`` days
    (Contacts scope). Reads at most 3,000 contacts."""
    people: list[dict] = []
    params = {"personFields": "names,birthdays", "pageSize": 1000}
    for _ in range(3):
        r = await _request(http, user_id, "contacts", "GET", f"{PEOPLE}/people/me/connections", params=params)
        body = r.json()
        people += body.get("connections", [])
        if not body.get("nextPageToken"):
            break
        params = {**params, "pageToken": body["nextPageToken"]}
    return upcoming(people, today, days)


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

    async def gmail_replies_owed() -> str | ToolOutput:
        from harness.connectors.replies import OWED_AFTER_H, replies_owed
        items = await replies_owed(user_id, datetime.now(UTC), http)
        if not items:
            return f"Nobody has been waiting more than {OWED_AFTER_H} hours for a reply from the user."
        lines = [f"- {r['from']} <{r['email']}>: {r['subject']} — waiting {r['waiting_days']} day(s) [thread {r['thread_id']}]"
                 for r in items]
        return ToolOutput(f"{len(items)} email(s) waiting for the user's reply, longest first "
                          "(use gmail__get_thread for the full text before drafting):\n" + "\n".join(lines),
                          ui={"kind": "gmail_messages", "query": "replies you owe",
                              "messages": [{"id": r["thread_id"], "thread_id": r["thread_id"], "from": r["from"],
                                            "subject": r["subject"], "snippet": r["snippet"], "date": r["received"],
                                            "labels": [], "unread": r["unread"]} for r in items]})

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

    # ------------------------------------------------- calendar: free time, changes
    async def calendar_find_free_time(time_min: str, time_max: str, duration_minutes: int = 30,
                                      day_start: str = "09:00", day_end: str = "18:00",
                                      timezone: str = "UTC", calendar_id: str = "primary") -> str | ToolOutput:
        from zoneinfo import ZoneInfo
        tz = ZoneInfo(timezone or "UTC")
        r = await call("calendar", "POST", f"{CALENDAR}/freeBusy",
                       json_body={"timeMin": time_min, "timeMax": time_max, "timeZone": timezone or "UTC",
                                  "items": [{"id": calendar_id}]})
        busy = [(datetime.fromisoformat(b["start"].replace("Z", "+00:00")), datetime.fromisoformat(b["end"].replace("Z", "+00:00")))
                for b in r.json().get("calendars", {}).get(calendar_id, {}).get("busy", [])]
        slots = free_slots(datetime.fromisoformat(time_min.replace("Z", "+00:00")),
                           datetime.fromisoformat(time_max.replace("Z", "+00:00")), busy,
                           int(duration_minutes or 30), day_start, day_end, tz)
        if not slots:
            return f"No free {duration_minutes}-minute slots between {day_start} and {day_end} in that range."
        lines = [f"{a.strftime('%a %d %b %H:%M')}–{b.strftime('%H:%M')}" for a, b in slots[:20]]
        return ToolOutput(f"Free slots ({timezone}, at least {duration_minutes} min):\n" + "\n".join(lines),
                          ui={"kind": "calendar_events", "created": False, "free": True,
                              "events": [{"summary": "Free", "start": a.isoformat(), "end": b.isoformat()} for a, b in slots[:20]]})

    async def calendar_update_event(event_id: str, start: str | None = None, end: str | None = None,
                                    summary: str | None = None, location: str | None = None,
                                    description: str | None = None, timezone: str | None = None,
                                    calendar_id: str = "primary") -> str | ToolOutput:
        body: dict = {}
        for k, v in (("summary", summary), ("location", location), ("description", description)):
            if v is not None:
                body[k] = v
        for k, v in (("start", start), ("end", end)):
            if v:
                body[k] = {"date": v} if len(v) == 10 else {"dateTime": v, **({"timeZone": timezone} if timezone else {})}
        if not body:
            return "Nothing to change: give a new start/end, summary, location or description."
        r = await call("calendar", "PATCH", f"{CALENDAR}/calendars/{calendar_id}/events/{event_id}", json_body=body)
        e = r.json()
        s0 = e.get("start", {}).get("dateTime") or e.get("start", {}).get("date", "")
        e0 = e.get("end", {}).get("dateTime") or e.get("end", {}).get("date", "")
        return ToolOutput(f"Event updated: {e.get('summary')} now {s0} → {e0}",
                          ui={"kind": "calendar_events", "created": True,
                              "events": [{"id": e.get("id"), "summary": e.get("summary"), "start": s0, "end": e0,
                                          "all_day": len(s0) == 10, "location": e.get("location"), "link": e.get("htmlLink")}]})

    async def calendar_delete_event(event_id: str, calendar_id: str = "primary") -> str:
        await call("calendar", "DELETE", f"{CALENDAR}/calendars/{calendar_id}/events/{event_id}")
        return f"Deleted event {event_id}."

    # -------------------------------------------------------------- sheets
    async def sheets_find(query: str = "", max_results: int = 10) -> str:
        q = "mimeType='application/vnd.google-apps.spreadsheet' and trashed=false"
        if query.strip():
            q += " and name contains '" + query.replace("\\", "").replace("'", "\\'") + "'"
        r = await call("sheets", "GET", f"{DRIVE}/files", params={
            "q": q, "pageSize": max(1, min(int(max_results or 10), 25)), "orderBy": "modifiedTime desc",
            "fields": "files(id,name,modifiedTime,webViewLink)"})
        found = r.json().get("files", [])
        if not found:
            return "No spreadsheets found" + (f" matching {query!r}." if query else ".")
        return "\n".join(f"[{f['id']}] {f['name']} (modified {f.get('modifiedTime', '')[:10]})" for f in found)

    async def sheets_read(spreadsheet_id: str, range: str = "") -> str | ToolOutput:  # noqa: A002
        if not range:
            meta = (await call("sheets", "GET", f"{SHEETS}/{spreadsheet_id}",
                               params={"fields": "properties.title,sheets.properties.title"})).json()
            tabs = [t["properties"]["title"] for t in meta.get("sheets", [])]
            range = f"'{tabs[0]}'!A1:Z200" if tabs else "A1:Z200"  # noqa: A001
        r = await call("sheets", "GET", f"{SHEETS}/{spreadsheet_id}/values/{range}",
                       params={"valueRenderOption": "UNFORMATTED_VALUE", "dateTimeRenderOption": "FORMATTED_STRING"})
        rows = r.json().get("values", [])
        if not rows:
            return f"The range {range} is empty."
        width = max(len(x) for x in rows)
        rows = [[*x, *[None] * (width - len(x))] for x in rows[:200]]
        text = "\n".join(" | ".join("" if v is None else str(v) for v in x) for x in rows)
        return ToolOutput(f"{r.json().get('range', range)} ({len(rows)} rows):\n{text[:MAX_TEXT]}",
                          ui={"kind": "table", "title": r.json().get("range", range), "rows": rows[:50]})

    async def sheets_append_rows(spreadsheet_id: str, rows: list[list], sheet: str = "") -> str | ToolOutput:
        target = f"'{sheet}'!A1" if sheet else "A1"
        r = await call("sheets", "POST", f"{SHEETS}/{spreadsheet_id}/values/{target}:append",
                       params={"valueInputOption": "USER_ENTERED", "insertDataOption": "INSERT_ROWS"},
                       json_body={"values": rows})
        upd = r.json().get("updates", {})
        return ToolOutput(f"Added {upd.get('updatedRows', len(rows))} row(s) at {upd.get('updatedRange', target)}.",
                          ui={"kind": "table", "title": f"Added to {upd.get('updatedRange', 'the sheet')}", "rows": rows[:50]})

    async def sheets_create(title: str, rows: list[list] | None = None) -> str:
        body: dict = {"properties": {"title": title}}
        if rows:
            body["sheets"] = [{"data": [{"rowData": [{"values": [
                {"userEnteredValue": {"numberValue": v} if isinstance(v, (int, float)) and not isinstance(v, bool)
                 else {"stringValue": "" if v is None else str(v)}} for v in row]} for row in rows]}]}]
        r = await call("sheets", "POST", SHEETS, json_body=body)
        d = r.json()
        return f"Created spreadsheet '{title}' [{d.get('spreadsheetId')}]: {d.get('spreadsheetUrl', '')}"

    # ------------------------------------------------------------ contacts
    async def contacts_search(query: str, max_results: int = 5) -> str | ToolOutput:
        mask = "names,emailAddresses,phoneNumbers"
        size = max(1, min(int(max_results or 5), 10))
        people: list[dict] = []
        for path, field in (("people:searchContacts", "results"), ("otherContacts:search", "results")):
            # Google wants an empty "warm-up" search before the first real one (it builds the cache)
            await call("contacts", "GET", f"{PEOPLE}/{path}", params={"query": "", "readMask": mask, "pageSize": 1})
            r = await call("contacts", "GET", f"{PEOPLE}/{path}", params={"query": query, "readMask": mask, "pageSize": size})
            for res in r.json().get(field, []):
                p = res.get("person", {})
                emails = [e.get("value") for e in p.get("emailAddresses", []) if e.get("value")]
                if not emails and not p.get("phoneNumbers"):
                    continue
                people.append({"name": (p.get("names") or [{}])[0].get("displayName") or (emails[0] if emails else ""),
                               "emails": emails, "phones": [x.get("value") for x in p.get("phoneNumbers", []) if x.get("value")]})
        seen, unique = set(), []
        for p in people:
            key = (p["emails"] or [p["name"]])[0].lower()
            if key not in seen:
                seen.add(key)
                unique.append(p)
        if not unique:
            return f"No contact matching {query!r}. Ask the user for the email address."
        return ToolOutput("\n".join(f"{p['name']}: {', '.join(p['emails']) or '-'}" + (f" · {', '.join(p['phones'])}" if p['phones'] else "")
                                    for p in unique[:size]),
                          ui={"kind": "contacts", "people": unique[:size]})

    obj = {"type": "object"}
    return [
        Tool(name="gmail__search_messages",
             description="Search the user's Gmail. `query` uses Gmail search syntax (e.g. 'newer_than:1d', "
                         "'from:alice is:unread', 'subject:invoice'). Returns sender, subject, date, labels and a snippet; "
                         "use gmail__get_thread for full text.",
             parameter={**obj, "properties": {"query": {"type": "string"}, "max_results": {"type": "integer", "minimum": 1, "maximum": 25},
                                              "label": {"type": "string", "description": "e.g. INBOX, UNREAD, STARRED"}}},
             handler=_handler("gmail", gmail_search)),
        Tool(name="gmail__replies_owed",
             description="Emails waiting for the user's reply: people who wrote to them directly (not newsletters or "
                         "notifications) and haven't had an answer for over a day, longest wait first. Use for "
                         "'who am I waiting to reply to', 'what do I owe', and before drafting catch-up replies.",
             parameter={**obj, "properties": {}},
             handler=_handler("gmail", gmail_replies_owed)),
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
             description="SEND an email from the user's Gmail. Only when the user explicitly asked to send. The user approves it on a card before it runs, so call it when asked.",
             parameter={**obj, "properties": {"to": {"type": "string"}, "subject": {"type": "string"}, "body": {"type": "string"},
                                              "cc": {"type": "string"}, "thread_id": {"type": "string", "description": "reply in this thread"}},
                        "required": ["to", "subject", "body"]},
             handler=_handler("gmail", gmail_send_message)),
        Tool(name="gmail__send_draft", description="Send an existing Gmail draft by draft id. The user approves it on a card before it runs, so call it when asked.",
             parameter={**obj, "properties": {"draft_id": {"type": "string"}}, "required": ["draft_id"]},
             handler=_handler("gmail", gmail_send_draft)),
        Tool(name="calendar__list_events",
             description="Events on the user's Google Calendar. Defaults to the next 7 days; pass RFC3339 time_min/time_max for another range.",
             parameter={**obj, "properties": {"time_min": {"type": "string"}, "time_max": {"type": "string"}, "max_results": {"type": "integer"},
                                              "calendar_id": {"type": "string"}, "query": {"type": "string"}}},
             handler=_handler("calendar", calendar_list_events)),
        Tool(name="calendar__create_event",
             description="Create a calendar event. start/end are RFC3339 date-times (or YYYY-MM-DD for all-day). The user approves it on a card before it runs, so call it when asked.",
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
        Tool(name="docs__append_text", description="Append text to the end of a Google Doc. The user approves it on a card before it runs, so call it when asked.",
             parameter={**obj, "properties": {"document_id": {"type": "string"}, "text": {"type": "string"}}, "required": ["document_id", "text"]},
             handler=_handler("docs", docs_append_text)),
        Tool(name="calendar__find_free_time",
             description="Find free slots on the user's calendar between time_min and time_max (RFC3339), at least "
                         "duration_minutes long, within day_start–day_end (HH:MM) in `timezone` (the user's). Use for "
                         "'when am I free Thursday?' or before proposing a meeting time.",
             parameter={**obj, "properties": {"time_min": {"type": "string"}, "time_max": {"type": "string"},
                                              "duration_minutes": {"type": "integer"}, "day_start": {"type": "string"},
                                              "day_end": {"type": "string"}, "timezone": {"type": "string"},
                                              "calendar_id": {"type": "string"}},
                        "required": ["time_min", "time_max"]},
             handler=_handler("calendar", calendar_find_free_time)),
        Tool(name="calendar__update_event",
             description="Change an event (move it, rename it, change place/notes) by event id from calendar__list_events. "
                         "Only pass the fields that change. The user approves it on a card before it runs, so call it when asked.",
             parameter={**obj, "properties": {"event_id": {"type": "string"}, "start": {"type": "string"}, "end": {"type": "string"},
                                              "summary": {"type": "string"}, "location": {"type": "string"},
                                              "description": {"type": "string"}, "timezone": {"type": "string"},
                                              "calendar_id": {"type": "string"}},
                        "required": ["event_id"]},
             handler=_handler("calendar", calendar_update_event)),
        Tool(name="calendar__delete_event",
             description="Delete (cancel) an event by event id. The user approves it on a card before it runs, so call it when asked.",
             parameter={**obj, "properties": {"event_id": {"type": "string"}, "calendar_id": {"type": "string"}},
                        "required": ["event_id"]},
             handler=_handler("calendar", calendar_delete_event)),
        Tool(name="sheets__find_spreadsheets",
             description="Find the user's Google Sheets by name (newest first). Returns ids for the other sheets__ tools.",
             parameter={**obj, "properties": {"query": {"type": "string"}, "max_results": {"type": "integer"}}},
             handler=_handler("sheets", sheets_find)),
        Tool(name="sheets__read_range",
             description="Read cells from a Google Sheet. `range` in A1 notation, e.g. \"'Budget'!A1:D50\"; omit it for the first tab.",
             parameter={**obj, "properties": {"spreadsheet_id": {"type": "string"}, "range": {"type": "string"}},
                        "required": ["spreadsheet_id"]},
             handler=_handler("sheets", sheets_read)),
        Tool(name="sheets__append_rows",
             description="Add rows to the end of a Google Sheet tab (`sheet` = tab name, default the first). Read the "
                         "sheet first so the columns line up. The user approves it on a card before it runs, so call it when asked.",
             parameter={**obj, "properties": {"spreadsheet_id": {"type": "string"}, "sheet": {"type": "string"},
                                              "rows": {"type": "array", "items": {"type": "array", "items": {}}}},
                        "required": ["spreadsheet_id", "rows"]},
             handler=_handler("sheets", sheets_append_rows)),
        Tool(name="sheets__create_spreadsheet",
             description="Create a new Google Sheet, optionally with starting rows (first row = header). The user approves it on a card before it runs, so call it when asked.",
             parameter={**obj, "properties": {"title": {"type": "string"},
                                              "rows": {"type": "array", "items": {"type": "array", "items": {}}}},
                        "required": ["title"]},
             handler=_handler("sheets", sheets_create)),
        Tool(name="contacts__search",
             description="Look up people in the user's Google Contacts (and people they have emailed) by name, to get "
                         "an email address or phone number. Use before emailing someone by name.",
             parameter={**obj, "properties": {"query": {"type": "string"}, "max_results": {"type": "integer"}},
                        "required": ["query"]},
             handler=_handler("contacts", contacts_search)),
    ]


