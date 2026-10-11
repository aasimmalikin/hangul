# ruff: noqa: F811  -- pytest injects the imported `billing` fixture by parameter name
"""Google Meet: a Meet link on calendar events (Calendar's conferenceData, no
new scope), and the Meet app (instant links, recent calls, transcripts) over
the Meet REST API. Both are Plus and up."""
import asyncio
import json

import httpx

from harness import provenance
from harness.api.routes.ask import _policy
from harness.billing import entitlements
from harness.connectors import auto
from harness.connectors import registry as creg
from harness.connectors.google_rest import make_google_tools, meet_link
from harness.db.billing import Account
from harness.integrations import google_oauth as go
from harness.tools.dispatch import dispatch
from tests.unit.test_billing import billing  # noqa: F401
from tests.unit.test_google_rest import FakeTokens

LINK = "https://meet.google.com/abc-defg-hij"


def call(tools, name, **args):
    r = asyncio.run(dispatch(tools[name], args))
    return r.content, r.ui


def api(seen, *, transcript=True):
    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(req)
        p, m = req.url.path, req.method
        # ----- calendar
        if p.endswith("/events") and m == "POST":
            body = json.loads(req.content)
            e = {"id": "ev9", "summary": body["summary"], "htmlLink": "https://calendar.google.com/ev9"}
            if "conferenceData" in body and req.url.params.get("conferenceDataVersion") == "1":
                e["hangoutLink"] = LINK
            return httpx.Response(200, json=e)
        if p.endswith("/events/ev1") and m == "PATCH":
            body = json.loads(req.content)
            e = {"id": "ev1", "summary": "Standup", "start": {"dateTime": "2026-10-09T10:00:00+05:30"},
                 "end": {"dateTime": "2026-10-09T10:30:00+05:30"}}
            if "conferenceData" in body:
                e["conferenceData"] = {"entryPoints": [{"entryPointType": "phone", "uri": "tel:+1"},
                                                       {"entryPointType": "video", "uri": LINK}]}
            return httpx.Response(200, json=e)
        if p.endswith("/events") and m == "GET":
            return httpx.Response(200, json={"items": [
                {"id": "a", "summary": "Call with Priya", "hangoutLink": LINK,
                 "start": {"dateTime": "2026-10-09T10:00:00+05:30"}, "end": {"dateTime": "2026-10-09T10:30:00+05:30"}},
                {"id": "b", "summary": "Lunch", "start": {"dateTime": "2026-10-09T13:00:00+05:30"},
                 "end": {"dateTime": "2026-10-09T14:00:00+05:30"}}]})
        # ----- meet
        if p == "/v2/spaces" and m == "POST":
            return httpx.Response(200, json={"name": "spaces/s1", "meetingUri": LINK, "meetingCode": "abc-defg-hij"})
        if p == "/v2/spaces/s1":
            return httpx.Response(200, json={"name": "spaces/s1", "meetingCode": "abc-defg-hij"})
        if p == "/v2/conferenceRecords":
            return httpx.Response(200, json={"conferenceRecords": [
                {"name": "conferenceRecords/r1", "space": "spaces/s1",
                 "startTime": "2026-10-07T09:00:00Z", "endTime": "2026-10-07T09:42:00Z"}]})
        if p == "/v2/conferenceRecords/r1":
            return httpx.Response(200, json={"name": "conferenceRecords/r1", "space": "spaces/s1",
                                             "startTime": "2026-10-07T09:00:00Z", "endTime": "2026-10-07T09:42:00Z"})
        if p == "/v2/conferenceRecords/r1/participants":
            return httpx.Response(200, json={"participants": [
                {"name": "conferenceRecords/r1/participants/p1", "signedinUser": {"displayName": "Rahul"}},
                {"name": "conferenceRecords/r1/participants/p2", "anonymousUser": {"displayName": "Guest"}}]})
        if p == "/v2/conferenceRecords/r1/transcripts":
            return httpx.Response(200, json={"transcripts": [
                {"name": "conferenceRecords/r1/transcripts/t1", "state": "FILE_GENERATED",
                 "docsDestination": {"exportUri": "https://docs.google.com/document/d/x"}}] if transcript else []})
        if p == "/v2/conferenceRecords/r1/transcripts/t1/entries":
            if not req.url.params.get("pageToken"):
                return httpx.Response(200, json={"nextPageToken": "n2", "transcriptEntries": [
                    {"participant": "conferenceRecords/r1/participants/p1", "text": "I'll send the quote by Friday."}]})
            return httpx.Response(200, json={"transcriptEntries": [
                {"participant": "conferenceRecords/r1/participants/p2", "text": "Great, thanks."}]})
        return httpx.Response(404, json={"error": {"message": f"unexpected {m} {p}"}})
    return handler


def tools(**kw):
    seen: list[httpx.Request] = []
    go.set_google_tokens(FakeTokens())
    http = httpx.AsyncClient(transport=httpx.MockTransport(api(seen, **kw)))
    return {t.name: t for t in make_google_tools("7", http=http)}, seen


# ------------------------------------------------- part 1: links on events

def test_create_event_with_meet_asks_calendar_for_a_meet_link():
    t, seen = tools()
    text, ui = call(t, "calendar__create_event", summary="Call with Priya", start="2026-10-09T10:00:00+05:30",
                    end="2026-10-09T10:30:00+05:30", meet=True)
    req = seen[-1]
    body = json.loads(req.content)
    assert req.url.params["conferenceDataVersion"] == "1"
    assert body["conferenceData"]["createRequest"]["conferenceSolutionKey"] == {"type": "hangoutsMeet"}
    assert body["conferenceData"]["createRequest"]["requestId"]          # unique per request
    assert LINK in text and ui["events"][0]["meet"] == LINK


def test_create_event_without_meet_sends_no_conference_data():
    t, seen = tools()
    text, ui = call(t, "calendar__create_event", summary="Lunch", start="2026-10-09T13:00:00+05:30",
                    end="2026-10-09T14:00:00+05:30")
    assert "conferenceData" not in json.loads(seen[-1].content)
    assert "conferenceDataVersion" not in seen[-1].url.params
    assert "Meet" not in text and ui["events"][0]["meet"] is None


def test_add_meet_to_an_existing_event_reads_the_video_entry_point():
    t, seen = tools()
    text, ui = call(t, "calendar__update_event", event_id="ev1", add_meet=True)
    assert json.loads(seen[-1].content).keys() == {"conferenceData"}       # nothing else changed
    assert LINK in text and ui["events"][0]["meet"] == LINK


def test_listed_events_carry_their_meet_link():
    t, _ = tools()
    text, ui = call(t, "calendar__list_events")
    assert f"google meet: {LINK}" in text
    assert [e["meet"] for e in ui["events"]] == [LINK, None]


def test_meet_link_ignores_non_meet_entry_points():
    assert meet_link({"conferenceData": {"entryPoints": [{"entryPointType": "video", "uri": "https://zoom.us/j/1"}]}}) is None
    assert meet_link({}) is None


# ------------------------------------------------------- part 2: the Meet app

def test_instant_meeting():
    t, seen = tools()
    text, ui = call(t, "meet__create_meeting")
    assert seen[-1].method == "POST" and seen[-1].url.path == "/v2/spaces"
    assert LINK in text and ui == {"kind": "meet_link", "uri": LINK, "code": "abc-defg-hij"}


def test_recent_meetings_with_people_and_transcripts():
    t, seen = tools()
    text, ui = call(t, "meet__recent_meetings", days=3)
    first = next(r for r in seen if r.url.path == "/v2/conferenceRecords")
    assert first.url.params["filter"].startswith('start_time>="')
    m = ui["meetings"][0]
    assert m == {"id": "r1", "code": "abc-defg-hij", "start": "2026-10-07T09:00:00Z", "end": "2026-10-07T09:42:00Z",
                 "minutes": 42, "participants": ["Guest", "Rahul"], "transcript": True}
    assert "42 min" in text and "Rahul" in text


def test_transcript_by_meeting_link_pages_through_entries():
    t, seen = tools()
    text, ui = call(t, "meet__get_transcript", meeting=LINK)
    lookup = next(r for r in seen if r.url.path == "/v2/conferenceRecords")
    assert lookup.url.params["filter"] == 'space.meeting_code = "abc-defg-hij"'
    assert "Rahul: I'll send the quote by Friday." in text and "Guest: Great, thanks." in text
    assert [x["who"] for x in ui["lines"]] == ["Rahul", "Guest"]
    assert ui["doc"] == "https://docs.google.com/document/d/x" and ui["minutes"] == 42


def test_no_transcript_is_said_plainly():
    t, _ = tools(transcript=False)
    text, ui = call(t, "meet__get_transcript", meeting="latest")
    assert "no transcript" in text and "Workspace" in text and ui is None


def test_a_meeting_id_cannot_reach_other_paths():
    t, seen = tools()
    text, _ = call(t, "meet__get_transcript", meeting="r1/../../spaces/s1")
    assert text.startswith("GOOGLE_API_ERROR (400)")
    assert not seen                                   # nothing was requested


# ------------------------------------------------- plans, switches, policy

def test_meet_is_its_own_switch_with_its_own_scopes():
    assert "meet" in creg.GOOGLE_PRODUCTS
    assert go.WORKSPACE_SCOPES["meet"] == ("https://www.googleapis.com/auth/meetings.space.created",
                                           "https://www.googleapis.com/auth/meetings.space.readonly")
    assert {t.name for t in creg.BUILTIN["meet"].tools("7")} == {
        "meet__create_meeting", "meet__recent_meetings", "meet__get_transcript"}
    assert go.connected_products(go.GoogleGrant("r", set(go.WORKSPACE_SCOPES["calendar"]))) == ["calendar"]


def test_meet_is_plus_and_pro_only(billing):
    names = ["meet__create_meeting", "meet__recent_meetings", "meet__get_transcript", "calendar__create_event",
             "calendar__update_event", "calendar__list_events"]
    t, _ = tools()
    stubs = {x.name for x in entitlements.gate_tools("7", [t[n] for n in names]) if x.upgrade_stub}
    assert stubs == set(names) - {"calendar__list_events"}            # Free: upgrade cards
    for plan in ("plus", "pro"):
        billing["accounts"]["7"] = Account(user_id="7", plan=plan)
        assert not any(x.upgrade_stub for x in entitlements.gate_tools("7", [t[n] for n in names]))


def test_meet_runs_without_a_tap_and_a_new_link_is_kept():
    assert {n: _policy.decide(n).name for n in ("meet__create_meeting", "meet__get_transcript")} == {
        "meet__create_meeting": "ALLOW", "meet__get_transcript": "ALLOW"}
    assert provenance.app_for("meet__create_meeting") == "Meet"
    assert provenance.app_for("meet__get_transcript") is None          # reads are never logged
    assert provenance.describe("meet__create_meeting", {}, done=True) == "Made a Google Meet link"


def test_meet_words_switch_on_the_right_apps():
    assert auto.route("summarise the transcript of yesterday's call", ["calendar", "meet"]) == ["meet"]
    assert auto.route("set up a video call with Priya tomorrow at 4", ["calendar", "meet"]) == ["calendar", "meet"]
    assert auto.route("give me a google meet link", ["gmail"]) == []      # never an unconnected app
