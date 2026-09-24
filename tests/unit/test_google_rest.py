"""The Google Workspace connector over REST, against mocked Google APIs."""

import asyncio
import base64
import json

import httpx

from harness.connectors import registry as creg
from harness.connectors.google_rest import _body_text, make_google_tools
from harness.integrations import google_oauth as go
from harness.tools.dispatch import dispatch


def run(coro):
    return asyncio.run(coro)


def call(tools, name, **args):
    """Through dispatch(), like the loop: returns (text, ui)."""
    r = asyncio.run(dispatch(tools[name], args))
    return r.content, r.ui


class FakeTokens:
    def __init__(self):
        self.calls = 0
        self.forgot = 0
        self.fail_product = None

    async def access_token(self, user_id, *, product=None):
        self.calls += 1
        if product == self.fail_product:
            raise go.GoogleNotConnected(f"Google {product} scopes were not granted; reconnect Google Workspace")
        return f"ya29-{user_id}-{self.calls}"

    def forget(self, user_id):
        self.forgot += 1


def b64(s: str) -> str:
    return base64.urlsafe_b64encode(s.encode()).decode()


def google_api(seen: list[httpx.Request]):
    """A stand-in for gmail/calendar/drive/docs endpoints."""
    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(req)
        path = req.url.path
        if req.headers.get("authorization") == "Bearer expired":
            return httpx.Response(401, json={"error": {"message": "Invalid Credentials"}})
        if path.endswith("/users/me/messages") and req.method == "GET":
            return httpx.Response(200, json={"messages": [{"id": "m1", "threadId": "t1"}, {"id": "m2", "threadId": "t2"}]})
        if path.endswith(("/messages/m1", "/messages/m2")):
            mid = path.rsplit("/", 1)[1]
            return httpx.Response(200, json={"id": mid, "threadId": "t1", "snippet": f"snippet {mid}", "labelIds": ["INBOX", "UNREAD"],
                                             "payload": {"headers": [{"name": "From", "value": "alice@example.com"}, {"name": "Subject", "value": f"Hello {mid}"},
                                                                     {"name": "Date", "value": "Fri, 19 Sep 2026 09:00:00 +0000"}, {"name": "To", "value": "me@example.com"}]}})
        if path.endswith("/threads/t1"):
            return httpx.Response(200, json={"messages": [{"id": "m1", "threadId": "t1", "labelIds": [],
                "payload": {"headers": [{"name": "From", "value": "alice@example.com"}, {"name": "Subject", "value": "Hello"}],
                            "mimeType": "multipart/alternative",
                            "parts": [{"mimeType": "text/html", "body": {"data": b64("<p>Hi <b>there</b></p><script>x()</script>")}},
                                      {"mimeType": "text/plain", "body": {"data": b64("Hi there\nplain")}}]}}]})
        if path.endswith("/messages/send") and req.method == "POST":
            return httpx.Response(200, json={"id": "sent1", "threadId": json.loads(req.content).get("threadId")})
        if path.endswith("/drafts/send") and req.method == "POST":
            return httpx.Response(200, json={"id": "sent2"})
        if path.endswith("/drafts") and req.method == "POST":
            raw = json.loads(req.content)["message"]["raw"]
            mime = base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4)).decode()
            return httpx.Response(200, json={"id": "d1", "echo": mime})
        if "/calendars/primary/events" in path and req.method == "GET":
            return httpx.Response(200, json={"items": [{"id": "e1", "summary": "Standup", "start": {"dateTime": "2026-09-20T09:00:00Z"},
                                                        "end": {"dateTime": "2026-09-20T09:15:00Z"}, "attendees": [{"email": "bob@example.com"}]}]})
        if "/calendars/primary/events" in path and req.method == "POST":
            body = json.loads(req.content)
            return httpx.Response(200, json={"id": "e2", "summary": body["summary"], "htmlLink": "https://cal/e2"})
        if path == "/drive/v3/files" and req.method == "GET":
            return httpx.Response(200, json={"files": [{"id": "f1", "name": "Plan.docx", "mimeType": "application/vnd.google-apps.document",
                                                        "modifiedTime": "2026-09-18T10:00:00Z", "webViewLink": "https://drive/f1"}]})
        if path == "/drive/v3/files/f1":
            return httpx.Response(200, json={"id": "f1", "name": "Plan", "mimeType": "application/vnd.google-apps.document", "modifiedTime": "x"})
        if path == "/drive/v3/files/f1/export":
            return httpx.Response(200, text="Exported plan text " * 3)
        if path == "/v1/documents/doc1" and req.method == "GET":
            return httpx.Response(200, json={"title": "Notes", "body": {"content": [
                {"endIndex": 1}, {"endIndex": 12, "paragraph": {"elements": [{"textRun": {"content": "First line\n"}}]}},
                {"endIndex": 20, "paragraph": {"elements": [{"textRun": {"content": "Second\n"}}]}}]}})
        if path == "/v1/documents/doc1:batchUpdate":
            return httpx.Response(200, json={"replies": [{}]})
        if path.endswith("/messages/nope"):
            return httpx.Response(404, json={"error": {"message": "Requested entity was not found."}})
        if path.endswith("/messages/forbidden"):
            return httpx.Response(403, json={"error": {"message": "Request had insufficient authentication scopes."}})
        return httpx.Response(500, text="unexpected " + path)
    return handler


def tools_for_test(tokens=None):
    seen: list[httpx.Request] = []
    http = httpx.AsyncClient(transport=httpx.MockTransport(google_api(seen)))
    go.set_google_tokens(tokens or FakeTokens())
    tools = {t.name: t for t in make_google_tools("7", http=http)}
    return tools, seen


def test_gmail_search_and_thread_text():
    tools, seen = tools_for_test()
    try:
        out = call(tools, "gmail__search_messages", query="newer_than:1d", max_results=2)[0]
        assert "2 message(s)" in out and "Hello m1" in out and "snippet m2" in out and "INBOX, UNREAD" in out
        assert seen[0].url.params["q"] == "newer_than:1d" and seen[0].headers["authorization"].startswith("Bearer ya29-7")
        assert seen[1].url.params["format"] == "metadata"
        out, ui = call(tools, "gmail__get_thread", thread_id="t1")
        assert "Hi there\nplain" in out and "<b>" not in out            # text/plain preferred over html
        assert ui["kind"] == "gmail_thread" and ui["messages"][0]["body"] == "Hi there\nplain"
    finally:
        go.set_google_tokens(None)


def test_html_fallback_strips_tags_and_scripts():
    text = _body_text({"mimeType": "text/html", "body": {"data": b64("<p>Hi <b>there</b></p><script>evil()</script><br>next")}})
    assert "Hi there" in text and "evil" not in text and "next" in text and "<" not in text


def test_gmail_create_draft_builds_mime():
    tools, seen = tools_for_test()
    try:
        out = call(tools, "gmail__create_draft", to="bob@example.com", subject="Re: plan", body="Sounds good.", thread_id="t1")[0]
        assert "Draft created (id d1)" in out and "not sent" in out
        sent = json.loads(seen[-1].content)
        assert sent["message"]["threadId"] == "t1"
        mime = base64.urlsafe_b64decode(sent["message"]["raw"] + "==").decode()
        assert "To: bob@example.com" in mime and "Subject: Re: plan" in mime and "Sounds good." in mime
    finally:
        go.set_google_tokens(None)


def test_gmail_send_message_and_send_draft():
    tools, seen = tools_for_test()
    try:
        out, ui = call(tools, "gmail__send_message", to="bob@example.com", subject="Hi", body="Sent body", thread_id="t1")
        assert out.startswith("Email sent to bob@example.com") and ui == {"kind": "gmail_sent", "message_id": "sent1", "to": "bob@example.com",
                                                                           "cc": None, "subject": "Hi", "body": "Sent body"}
        assert seen[-1].url.path.endswith("/messages/send") and json.loads(seen[-1].content)["threadId"] == "t1"
        out, ui = call(tools, "gmail__send_draft", draft_id="d1")
        assert "Draft d1 sent" in out and ui["message_id"] == "sent2" and json.loads(seen[-1].content) == {"id": "d1"}
    finally:
        go.set_google_tokens(None)


def test_calendar_drive_docs():
    tools, seen = tools_for_test()
    try:
        out, ui = call(tools, "calendar__list_events")
        assert ui["kind"] == "calendar_events" and ui["events"][0]["summary"] == "Standup" and ui["events"][0]["attendees"] == ["bob@example.com"]
        assert "Standup" in out and "bob@example.com" in out and seen[-1].url.params["singleEvents"] == "true"
        out = call(tools, "calendar__create_event", summary="Dentist", start="2026-09-21", end="2026-09-21")[0]
        assert "Event created: Dentist" in out and json.loads(seen[-1].content)["start"] == {"date": "2026-09-21"}
        out = call(tools, "drive__search_files", query="plan")[0]
        assert "Plan.docx" in out and "name contains 'plan'" in seen[-1].url.params["q"]
        out = call(tools, "drive__get_file", file_id="f1")[0]
        assert "Exported plan text" in out and seen[-1].url.params["mimeType"] == "text/plain"
        out = call(tools, "docs__get_document", document_id="doc1")[0]
        assert out.startswith("# Notes") and "First line\nSecond" in out
        out = call(tools, "docs__append_text", document_id="doc1", text="Third")[0]
        assert "Appended 5 characters" in out
        req = json.loads(seen[-1].content)["requests"][0]["insertText"]
        assert req["location"]["index"] == 19 and req["text"] == "Third"
    finally:
        go.set_google_tokens(None)


def test_errors_become_actionable_text_and_401_retries():
    tokens = FakeTokens()
    tools, seen = tools_for_test(tokens)
    try:
        assert call(tools, "gmail__get_message", message_id="nope")[0].startswith("GOOGLE_API_ERROR (404)")
        assert call(tools, "gmail__get_message", message_id="forbidden")[0].startswith("GOOGLE_SCOPE_MISSING")
        tokens.fail_product = "calendar"
        assert call(tools, "calendar__list_events")[0].startswith("GOOGLE_NOT_CONNECTED")
    finally:
        go.set_google_tokens(None)

    class Expiring(FakeTokens):
        async def access_token(self, user_id, *, product=None):
            self.calls += 1
            return "expired" if self.calls == 1 else "fresh-token"
    exp = Expiring()
    tools, seen = tools_for_test(exp)
    try:
        out = call(tools, "gmail__get_thread", thread_id="t1")[0]
        assert "Hi there" in out and exp.forgot == 1 and len(seen) == 2       # 401 -> forget -> retry once
    finally:
        go.set_google_tokens(None)


def test_registry_exposes_google_as_per_user_builtin():
    cons = creg.all_connectors()
    g = cons["google"]
    assert g.kind == "builtin" and g.per_user and g.auth == "google"
    tools, note, _ = creg.tools_for(["google"], [], user_id="7")
    names = {t.name for t in tools}
    assert {"gmail__search_messages", "gmail__send_message", "gmail__send_draft", "calendar__list_events", "drive__search_files", "docs__get_document"} <= names
    assert "Google Workspace connector is ON" in note
    assert creg.tools_for(["google"], [], user_id=None)[0] == []          # per-user: no user, no tools
