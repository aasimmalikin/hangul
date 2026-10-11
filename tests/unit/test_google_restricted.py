"""Gmail and Drive (Google's restricted scopes) only for accounts on GOOGLE_RESTRICTED_EMAILS,
until the yearly CASA assessment is done; everything else needs only Google's free verification."""

import asyncio

from harness.connectors import registry as creg
from harness.connectors.google_rest import make_google_tools, sheet_id
from harness.integrations import google_oauth as go
from tests.unit.test_google_rest import FakeTokens

GMAIL = set(go.WORKSPACE_SCOPES["gmail"])
CAL = set(go.WORKSPACE_SCOPES["calendar"])
DRIVE = set(go.WORKSPACE_SCOPES["drive"])


def _listed(monkeypatch, emails: str = "tester@example.com"):
    monkeypatch.setenv("GOOGLE_RESTRICTED_EMAILS", emails)
    monkeypatch.setenv("ADMIN_EMAILS", "boss@example.com")


def test_star_keeps_everyone_on_every_product(monkeypatch):
    monkeypatch.setenv("GOOGLE_RESTRICTED_EMAILS", "*")
    assert go.restricted_allowed(None) and go.scopes_for(True) == [s for s in go.ALL_SCOPES
                                                          if not any(s in go.WORKSPACE_SCOPES[p] for p in go.UNOFFERED_PRODUCTS)]
    assert go.connected_products(go.GoogleGrant("r", GMAIL | CAL)) == ["gmail", "calendar"]


def test_only_listed_accounts_and_admins_get_gmail_and_drive(monkeypatch):
    _listed(monkeypatch)
    assert go.restricted_allowed("Tester@Example.com ") and go.restricted_allowed("boss@example.com")
    assert not go.restricted_allowed("someone@else.com") and not go.restricted_allowed(None)
    grant = go.GoogleGrant("r", GMAIL | CAL | DRIVE | {go.SHEETS_SEARCH_SCOPE}, email="someone@else.com")
    assert go.connected_products(grant) == ["calendar"]            # an old grant is switched off too
    assert "sheets_search" not in go.capabilities(grant)
    grant.email = "tester@example.com"
    assert go.connected_products(grant) == ["gmail", "calendar", "drive"]
    assert "sheets_search" in go.capabilities(grant)


def test_scopes_without_restricted_products_are_only_sensitive_ones(monkeypatch):
    scopes = go.scopes_for(False)
    for s in (*GMAIL, *DRIVE, go.SHEETS_SEARCH_SCOPE):
        assert s not in scopes
    for p in ("calendar", "contacts", "sheets"):
        assert set(go.WORKSPACE_SCOPES[p]) <= set(scopes)
    for p in go.UNOFFERED_PRODUCTS:   # Docs and Meet are no longer asked for
        assert not set(go.WORKSPACE_SCOPES[p]) & set(scopes)
        assert not set(go.WORKSPACE_SCOPES[p]) & set(go.scopes_for(True))


def test_status_reports_whether_restricted_products_are_offered(monkeypatch):
    _listed(monkeypatch)
    src = go.GoogleTokenSource()
    monkeypatch.setattr(go, "_load_grant", lambda uid: go.GoogleGrant("r", GMAIL | CAL, email="x@y.com") if uid == "1" else None)
    monkeypatch.setattr(go, "_user_email", lambda uid: "tester@example.com")
    st1 = asyncio.run(src.status("1"))
    assert st1 == {"connected": True, "products": ["calendar"], "restricted": False}
    assert asyncio.run(src.status("2"))["restricted"] is True       # not connected yet, but on the list


def test_catalogue_marks_gmail_and_drive_restricted():
    flags = {c["key"]: c["restricted"] for c in creg.available() if c.get("group") == "Google Workspace"}
    assert flags["gmail"] and flags["drive"]
    assert not any(flags[k] for k in ("calendar", "contacts", "sheets"))


def test_finding_a_sheet_by_name_without_drive_metadata_asks_for_the_link(monkeypatch):
    class NoSearch(FakeTokens):
        async def access_token(self, user_id, *, product=None):
            if product == "sheets_search":
                raise go.GoogleNotConnected("not granted")
            return await super().access_token(user_id, product=product)
    monkeypatch.setattr("harness.connectors.google_rest.google_tokens", lambda: NoSearch())
    tool = next(t for t in make_google_tools("7") if t.name == "sheets__find_spreadsheets")
    out = asyncio.run(tool.handler(query="Budget"))
    assert "paste the sheet's link" in out
    assert sheet_id("https://docs.google.com/spreadsheets/d/1AbC-d_9/edit#gid=0") == "1AbC-d_9"
    assert sheet_id(" 1AbC ") == "1AbC"
