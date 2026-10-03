"""Phase 3 Google tools against mocked Google APIs: calendar free time /
update / delete, Sheets find / read / append / create, Contacts search, the
new scopes and approval tiers, and the emailed daily brief."""
import asyncio
import json
from datetime import datetime
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import httpx

from harness import notify, scheduler
from harness.api.routes.ask import _policy
from harness.connectors import registry as creg
from harness.connectors.google_rest import free_slots, make_google_tools
from harness.integrations import google_oauth as go
from harness.tools.dispatch import dispatch
from tests.unit.test_google_rest import FakeTokens

IST = ZoneInfo("Asia/Kolkata")


def call(tools, name, **args):
    r = asyncio.run(dispatch(tools[name], args))
    return r.content, r.ui


def api(seen):
    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(req)
        p, m = req.url.path, req.method
        if p.endswith("/freeBusy"):
            return httpx.Response(200, json={"calendars": {"primary": {"busy": [
                {"start": "2026-10-08T04:30:00Z", "end": "2026-10-08T05:30:00Z"},      # 10:00–11:00 IST
                {"start": "2026-10-08T08:30:00Z", "end": "2026-10-08T10:30:00Z"}]}}})  # 14:00–16:00 IST
        if "/events/ev1" in p and m == "PATCH":
            body = json.loads(req.content)
            return httpx.Response(200, json={"id": "ev1", "summary": "Standup", "start": body["start"], "end": body["end"]})
        if "/events/ev1" in p and m == "DELETE":
            return httpx.Response(204)
        if p.endswith("/drive/v3/files"):
            return httpx.Response(200, json={"files": [{"id": "sh1", "name": "Budget 2026", "modifiedTime": "2026-10-01T10:00:00Z"}]})
        if p.endswith("/spreadsheets/sh1") and m == "GET":
            return httpx.Response(200, json={"sheets": [{"properties": {"title": "Sep"}}]})
        if "/values/" in p and p.endswith(":append"):
            return httpx.Response(200, json={"updates": {"updatedRows": 1, "updatedRange": "Sep!A4:C4"}})
        if "/values/" in p:
            return httpx.Response(200, json={"range": "Sep!A1:C3", "values": [["Date", "Item", "Amount"], ["2026-09-01", "Rent", 15000], ["2026-09-03", "Lunch"]]})
        if p.endswith("/v4/spreadsheets") and m == "POST":
            return httpx.Response(200, json={"spreadsheetId": "new1", "spreadsheetUrl": "https://docs.google.com/spreadsheets/d/new1"})
        if p.endswith("people:searchContacts"):
            q = req.url.params.get("query")
            return httpx.Response(200, json={"results": [] if not q else [{"person": {
                "names": [{"displayName": "Priya Sharma"}], "emailAddresses": [{"value": "priya@example.com"}],
                "phoneNumbers": [{"value": "+91 98xxxxxx"}]}}]})
        if p.endswith("otherContacts:search"):
            q = req.url.params.get("query")
            return httpx.Response(200, json={"results": [] if not q else [
                {"person": {"emailAddresses": [{"value": "priya@example.com"}]}},          # duplicate: dropped
                {"person": {"names": [{"displayName": "Priya K"}], "emailAddresses": [{"value": "priyak@work.example"}]}}]})
        return httpx.Response(404, json={"error": {"message": f"unexpected {m} {p}"}})
    return handler


def tools():
    seen: list[httpx.Request] = []
    go.set_google_tokens(FakeTokens())
    http = httpx.AsyncClient(transport=httpx.MockTransport(api(seen)))
    return {t.name: t for t in make_google_tools("7", http=http)}, seen


# ------------------------------------------------------------- calendar

def test_free_slots_respect_working_hours_and_busy_blocks():
    day = datetime(2026, 10, 8, tzinfo=IST)
    busy = [(day.replace(hour=10), day.replace(hour=11)), (day.replace(hour=14), day.replace(hour=16))]
    slots = free_slots(day, day.replace(hour=23), busy, 30, "09:00", "18:00", IST)
    assert [(a.strftime("%H:%M"), b.strftime("%H:%M")) for a, b in slots] == [("09:00", "10:00"), ("11:00", "14:00"), ("16:00", "18:00")]
    assert free_slots(day, day.replace(hour=23), busy, 90, "09:00", "18:00", IST)[0][0].strftime("%H:%M") == "11:00"


def test_find_free_time_uses_freebusy_in_the_users_timezone():
    t, seen = tools()
    text, ui = call(t, "calendar__find_free_time", time_min="2026-10-08T00:00:00+05:30",
                    time_max="2026-10-08T23:59:00+05:30", duration_minutes=60, timezone="Asia/Kolkata")
    assert "Thu 08 Oct 09:00–10:00" in text and "11:00–14:00" in text and "16:00–18:00" in text
    assert ui["free"] is True and json.loads(seen[0].content)["timeZone"] == "Asia/Kolkata"


def test_move_and_delete_an_event():
    t, seen = tools()
    text, ui = call(t, "calendar__update_event", event_id="ev1", start="2026-10-08T16:00:00+05:30",
                    end="2026-10-08T16:30:00+05:30")
    assert "now 2026-10-08T16:00:00+05:30" in text and ui["created"]
    assert set(json.loads(seen[-1].content)) == {"start", "end"}            # only what changed
    assert "Nothing to change" in call(t, "calendar__update_event", event_id="ev1")[0]
    assert call(t, "calendar__delete_event", event_id="ev1")[0] == "Deleted event ev1."


# --------------------------------------------------------------- sheets

def test_find_read_append_create_sheets():
    t, seen = tools()
    assert "[sh1] Budget 2026" in call(t, "sheets__find_spreadsheets", query="budget")[0]
    assert "mimeType='application/vnd.google-apps.spreadsheet'" in seen[-1].url.params["q"]
    text, ui = call(t, "sheets__read_range", spreadsheet_id="sh1")
    assert ui["kind"] == "table" and ui["rows"][2] == ["2026-09-03", "Lunch", None]   # ragged rows padded
    assert "'Sep'!A1:Z200" in seen[-1].url.path
    text, ui = call(t, "sheets__append_rows", spreadsheet_id="sh1", sheet="Sep", rows=[["2026-10-02", "Lunch", 450]])
    assert text == "Added 1 row(s) at Sep!A4:C4." and seen[-1].url.params["valueInputOption"] == "USER_ENTERED"
    text, _ = call(t, "sheets__create_spreadsheet", title="Trip", rows=[["Item", "Cost"], ["Hotel", 4000]])
    assert "new1" in text
    cells = json.loads(seen[-1].content)["sheets"][0]["data"][0]["rowData"][1]["values"]
    assert cells == [{"userEnteredValue": {"stringValue": "Hotel"}}, {"userEnteredValue": {"numberValue": 4000}}]


def test_sheet_names_with_quotes_cannot_break_the_drive_query():
    t, seen = tools()
    call(t, "sheets__find_spreadsheets", query="o'brien' or name contains '")
    assert "name contains 'o\\'brien\\' or name contains \\''" in seen[-1].url.params["q"]


# ------------------------------------------------------------- contacts

def test_contact_search_merges_and_dedupes():
    t, seen = tools()
    text, ui = call(t, "contacts__search", query="priya")
    assert [p["name"] for p in ui["people"]] == ["Priya Sharma", "Priya K"]
    assert "priya@example.com" in text and "+91" in text
    warmups = [r for r in seen if r.url.params.get("query") == ""]
    assert len(warmups) == 2                                                  # Google's cache warm-up, per source


# ------------------------------------------------ products, scopes, tiers

def test_sheets_and_contacts_are_their_own_switches():
    assert {"sheets", "contacts"} <= set(creg.GOOGLE_PRODUCTS)
    assert "https://www.googleapis.com/auth/spreadsheets" in go.WORKSPACE_SCOPES["sheets"]
    assert all("readonly" in s for s in go.WORKSPACE_SCOPES["contacts"])
    sheet_tools = {t.name for t in creg.BUILTIN["sheets"].tools("7")}
    assert sheet_tools == {"sheets__find_spreadsheets", "sheets__read_range", "sheets__append_rows", "sheets__create_spreadsheet"}


def test_writes_need_approval_and_reads_do_not():
    needs = {n: _policy.decide(n).name for n in ("sheets__append_rows", "sheets__create_spreadsheet", "calendar__update_event",
                                                 "calendar__delete_event", "sheets__read_range", "contacts__search",
                                                 "calendar__find_free_time")}
    assert needs == {"sheets__append_rows": "NEEDS_APPROVAL", "sheets__create_spreadsheet": "NEEDS_APPROVAL",
                     "calendar__update_event": "NEEDS_APPROVAL", "calendar__delete_event": "NEEDS_APPROVAL",
                     "sheets__read_range": "ALLOW", "contacts__search": "ALLOW", "calendar__find_free_time": "ALLOW"}


# ------------------------------------------------------- the daily brief

def test_task_result_is_emailed_to_the_user(monkeypatch):
    sent = []
    monkeypatch.setattr(notify, "email_enabled", lambda: True)
    monkeypatch.setattr(notify, "user_email", lambda uid: "me@example.com")

    async def fake_send(to, subject, text, html=None):
        sent.append((to, subject, text, html))
        return True
    monkeypatch.setattr(notify, "send_email", fake_send)
    task = SimpleNamespace(id=1, user_id=7, title="Morning brief")
    assert asyncio.run(scheduler.email_result(task, "## Today\n- **9:00** Standup"))
    to, subject, text, html = sent[0]
    assert (to, subject) == ("me@example.com", "⏰ Morning brief")
    assert "<li><b>9:00</b> Standup</li>" in html and "Standup" in text


def test_brief_email_escapes_html_from_the_answer():
    _, _, html = notify.task_email("Brief", "<script>alert(1)</script> **ok**")
    assert "<script>" not in html and "&lt;script&gt;" in html and "<b>ok</b>" in html
