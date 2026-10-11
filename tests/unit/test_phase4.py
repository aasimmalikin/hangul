"""Phase 4: image generation (metered, Pro), maps & travel time (OSM, Plus),
GitHub / Notion / Slack over the vault (Pro), the connect endpoint that
checks a token before keeping it, and pattern-based plan gating."""
import asyncio
import base64
import json
from decimal import Decimal
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from harness.api.auth import get_current_user
from harness.api.routes import integrations as integ
from harness.billing import entitlements
from harness.billing.plans import PLANS, gate_for, plan_allows_tool
from harness.connectors import work_apps
from harness.db import billing as billing_db
from harness.db.billing import Account
from harness.tools.builtin import files, images, maps

PNG = b"\x89PNG\r\n\x1a\nfake"


def run(coro):
    return asyncio.run(coro)


# ---------------------------------------------------------------- images

@pytest.fixture
def folder(tmp_path, monkeypatch):
    monkeypatch.setattr(files, "SESSIONS", tmp_path)
    return files.user_folder("7")


def test_image_is_saved_shown_and_charged(folder, monkeypatch):
    calls, charged = [], []

    async def generate(**kw):
        calls.append(kw)
        return SimpleNamespace(data=[SimpleNamespace(b64_json=base64.b64encode(PNG).decode())])
    import harness.providers as providers
    monkeypatch.setattr(providers, "get_provider", lambda: SimpleNamespace(client=SimpleNamespace(images=SimpleNamespace(generate=generate))))
    monkeypatch.setattr(entitlements, "settle", lambda uid, cost, tid: charged.append((uid, cost)))
    out = run(images.make_generate_image_tool("7").handler(prompt="A watercolour of Pune at dawn", shape="landscape"))
    assert out.ui["kind"] == "image" and (folder / out.ui["name"]).read_bytes() == PNG
    assert calls[0]["size"] == "1536x1024" and calls[0]["quality"] == "high" and calls[0]["model"] == "gpt-image-1"
    assert charged == [("7", Decimal("0.25"))]


def test_image_refusal_is_explained(folder, monkeypatch):
    async def generate(**kw):
        raise RuntimeError("Your request was rejected as a result of our safety system.")
    import harness.providers as providers
    monkeypatch.setattr(providers, "get_provider", lambda: SimpleNamespace(client=SimpleNamespace(images=SimpleNamespace(generate=generate))))
    assert "content policy" in run(images.make_generate_image_tool("7").handler(prompt="something"))
    assert list(folder.glob("*.png")) == []


# ------------------------------------------------------------------ maps

def test_image_gets_a_longer_timeout_than_other_tools():
    from harness.tools.base import Tool
    from harness.tools.dispatch import dispatch

    assert images.make_generate_image_tool("7").timeout >= 120

    async def slow():
        await asyncio.sleep(0.2)
        return "drawn"

    patient = Tool("slow", "", {"type": "object", "properties": {}}, slow, timeout=1.0)
    hasty = Tool("slow", "", {"type": "object", "properties": {}}, slow, timeout=0.05)
    assert run(dispatch(patient, {})).content == "drawn"
    assert "timed out after 0.05s" in run(dispatch(hasty, {})).content


def test_travel_time_route_and_directions_link(monkeypatch):
    async def fake_nominatim(client, q, limit=5):
        return [{"lat": "18.5195", "lon": "73.8553", "display_name": "Shaniwarwada, Pune"}] if "Wada" in q else \
               [{"lat": "18.5289", "lon": "73.8743", "display_name": "Pune Junction, Pune"}]
    monkeypatch.setattr(maps, "_nominatim", fake_nominatim)

    class FakeClient:
        def __init__(self, *a, **k): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def get(self, url, **kw):
            assert "routed-foot" in url and "73.8553,18.5195;73.8743,18.5289" in url
            return SimpleNamespace(raise_for_status=lambda: None, json=lambda: {"routes": [{"distance": 2600, "duration": 2100}]})
    monkeypatch.setattr(maps.httpx, "AsyncClient", FakeClient)
    out = run(maps.travel_time("Shaniwar Wada, Pune", "Pune Railway Station", "walking"))
    assert out.ui["minutes"] == 35 and out.ui["km"] == 2.6
    assert "travelmode=walking" in out.ui["link"] and "Shaniwar+Wada%2C+Pune" in out.ui["link"]


def test_transit_hands_over_to_google_maps():
    out = run(maps.travel_time("Home", "Office", "transit"))
    assert "travelmode=transit" in out.ui["link"] and out.ui.get("minutes") is None


# ------------------------------------------------------------- work apps

class FakeVault:
    def __init__(self, replies):
        self.replies, self.calls = replies, []

    async def call(self, *, subject, provider, method, path, query=None, headers=None, body=None):
        self.calls.append(dict(provider=provider, method=method, path=path, query=query, headers=headers,
                               body=json.loads(body) if body else None))
        status, payload = self.replies.get((method, path), (404, {"message": "not found"}))
        if isinstance(status, Exception):
            raise status
        return SimpleNamespace(status=status, body=json.dumps(payload))


def with_vault(monkeypatch, replies):
    v = FakeVault(replies)
    import harness.vault as vault_mod
    monkeypatch.setattr(vault_mod, "current", lambda: v)
    return v


def tools(factory):
    return {t.name: t for t in factory("7")}


def test_github_my_work_and_search(monkeypatch):
    v = with_vault(monkeypatch, {("GET", "/search/issues"): (200, {"items": [{
        "repository_url": "https://api.github.com/repos/acme/app", "number": 12, "title": "Fix login", "state": "open",
        "html_url": "https://github.com/acme/app/pull/12", "pull_request": {}, "updated_at": "2026-10-01T10:00:00Z"}]})})
    out = run(tools(work_apps.make_github_tools)["github__my_work"].handler(kind="review_requests"))
    assert v.calls[0]["query"]["q"] == "is:open is:pr review-requested:@me"
    assert out.ui["items"][0] == {"repo": "acme/app", "number": 12, "title": "Fix login", "state": "open",
                                  "url": "https://github.com/acme/app/pull/12", "pr": True, "updated": "2026-10-01"}


def test_github_repo_must_be_owner_slash_name(monkeypatch):
    with_vault(monkeypatch, {})
    assert "owner/name" in run(tools(work_apps.make_github_tools)["github__create_issue"].handler(repo="justaname", title="x"))


def _item(repo, number, title, pr=False, updated="2026-10-01T10:00:00Z"):
    return {"repository_url": f"https://api.github.com/repos/{repo}", "number": number, "title": title, "state": "open",
            "html_url": f"https://github.com/{repo}/{'pull' if pr else 'issues'}/{number}", "updated_at": updated,
            **({"pull_request": {}} if pr else {})}


class SearchVault(FakeVault):
    """Answers /search/issues by query, so the parts of a merged search can differ."""
    def __init__(self, by_query, replies=None):
        super().__init__(replies or {})
        self.by_query = by_query

    async def call(self, *, subject, provider, method, path, query=None, headers=None, body=None):
        if path != "/search/issues":
            return await super().call(subject=subject, provider=provider, method=method, path=path, query=query,
                                      headers=headers, body=body)
        self.calls.append({"provider": provider, "method": method, "path": path, "query": query})
        got = self.by_query.get(query["q"], [])
        if isinstance(got, tuple):
            return SimpleNamespace(status=got[0], body=json.dumps(got[1]))
        return SimpleNamespace(status=200, body=json.dumps({"items": got}))


def test_github_search_names_a_type_or_searches_both(monkeypatch):
    v = SearchVault({"repo:a/b is:issue": [_item("a/b", 1, "Old bug", updated="2026-09-01T00:00:00Z")],
                     "repo:a/b is:pull-request": [_item("a/b", 2, "New fix", pr=True)]})
    import harness.vault as vault_mod
    monkeypatch.setattr(vault_mod, "current", lambda: v)
    out = run(tools(work_apps.make_github_tools)["github__search"].handler(query="repo:a/b"))
    assert [r["number"] for r in out.ui["items"]] == [2, 1]                     # merged, newest first
    run(tools(work_apps.make_github_tools)["github__search"].handler(query="repo:a/b is:pr"))
    assert v.calls[-1]["query"]["q"] == "repo:a/b is:pr"                         # typed: one call, unchanged


def test_github_waiting_on_me_checks_all_three(monkeypatch):
    shared = _item("a/b", 7, "Both assigned and mentioned")
    v = SearchVault({"is:open is:pr review-requested:@me": [_item("a/b", 9, "Review me", pr=True)],
                     "is:open assignee:@me is:issue": [shared],
                     "is:open assignee:@me is:pull-request": [],
                     "is:open mentions:@me is:issue": [shared],
                     "is:open mentions:@me is:pull-request": (500, {"message": "boom"})})
    import harness.vault as vault_mod
    monkeypatch.setattr(vault_mod, "current", lambda: v)
    out = run(tools(work_apps.make_github_tools)["github__my_work"].handler())
    assert "Waiting for your review" in out.text and "Assigned to you" in out.text
    assert "Could not check -- mentioning you" in out.text                     # one failure doesn't sink the rest
    assert sorted(r["number"] for r in out.ui["items"]) == [7, 9]               # deduplicated


def test_github_waiting_on_me_says_nothing_plainly(monkeypatch):
    import harness.vault as vault_mod
    monkeypatch.setattr(vault_mod, "current", lambda: SearchVault({}))
    out = run(tools(work_apps.make_github_tools)["github__my_work"].handler(kind="all"))
    assert isinstance(out, str) and out.count(": none") == 3


def test_github_my_repos_uses_the_login(monkeypatch):
    v = SearchVault({"user:octo is:open is:issue": [_item("octo/app", 3, "Bug")]},
                    {("GET", "/user"): (200, {"login": "octo"})})
    import harness.vault as vault_mod
    monkeypatch.setattr(vault_mod, "current", lambda: v)
    out = run(tools(work_apps.make_github_tools)["github__my_work"].handler(kind="repos"))
    assert "repositories octo owns" in out.text and out.ui["items"][0]["number"] == 3


def test_github_read_file_readme_folder_and_binary(monkeypatch):
    def enc(b):
        return base64.b64encode(b).decode()
    with_vault(monkeypatch, {
        ("GET", "/repos/a/b/readme"): (200, {"type": "file", "path": "README.md", "encoding": "base64",
                                             "content": enc(b"# Hello\nworld"), "html_url": "u"}),
        ("GET", "/repos/a/b/contents/src"): (200, [{"name": "z.py", "type": "file"}, {"name": "lib", "type": "dir"}]),
        ("GET", "/repos/a/b/contents/logo.png"): (200, {"type": "file", "path": "logo.png", "encoding": "base64",
                                                        "content": enc(b"\x89PNG\xff\xfe"), "html_url": "u"}),
    })
    t = tools(work_apps.make_github_tools)["github__read_file"]
    assert "# Hello\nworld" in run(t.handler(repo="https://github.com/a/b"))
    assert run(t.handler(repo="a/b", path="/src/")).endswith("lib/\nz.py")     # folders first
    assert "binary" in run(t.handler(repo="a/b", path="logo.png"))


def test_github_pr_changes_and_checks(monkeypatch):
    head = {"ref": "fix", "sha": "abc1234def"}
    with_vault(monkeypatch, {
        ("GET", "/repos/a/b/pulls/5"): (200, {"title": "Fix", "state": "open", "html_url": "u", "head": head,
                                              "base": {"ref": "main"}, "changed_files": 1, "additions": 2, "deletions": 1}),
        ("GET", "/repos/a/b/pulls/5/files"): (200, [{"filename": "x.py", "status": "modified", "additions": 2,
                                                     "deletions": 1, "patch": "@@\n-a\n+b\n" + "+c\n" * 2000}]),
        ("GET", "/repos/a/b/commits/abc1234def/check-runs"): (403, {"message": "Resource not accessible by personal access token"}),
        ("GET", "/repos/a/b/commits/abc1234def/status"): (200, {"statuses": [
            {"context": "ci/test", "state": "failure", "target_url": "https://ci/1"},
            {"context": "ci/lint", "state": "success"}]}),
    })
    t = tools(work_apps.make_github_tools)
    diff = run(t["github__pr_changes"].handler(repo="a/b", number=5))
    assert "fix → main" in diff and "modified x.py (+2 −1)" in diff and "[patch truncated]" in diff
    ci = run(t["github__checks"].handler(repo="a/b", number=5))
    assert ci.startswith("a/b#5 CI is failing on abc1234") and "failed: ci/test https://ci/1" in ci
    assert "check runs not readable" in ci and "permission" in ci              # a 403 here is a permission, not a bad token
    assert "not a pull request" in run(t["github__checks"].handler(repo="a/b", number=6))


def test_github_errors_say_what_to_do(monkeypatch):
    with_vault(monkeypatch, {("GET", "/search/issues"): (422, {"message": "Validation Failed", "errors": [
        {"message": "The listed users and repositories cannot be searched either because the resources do not exist "
                    "or you do not have permission to view them."}]})})
    out = run(tools(work_apps.make_github_tools)["github__search"].handler(query="repo:facebook/react is:issue"))
    assert out.startswith("GITHUB_NO_ACCESS")


def test_github_repo_accepts_links():
    assert work_apps._repo("https://github.com/a/b/issues/5") == "a/b"
    assert work_apps._repo("github.com/a/b/pull/7#issuecomment-1") == "a/b"
    assert work_apps._repo(" a/b ") == "a/b"
    for bad in ("justaname", "a/b/c", "https://example.com/a/b"):
        with pytest.raises(work_apps.AppError):
            work_apps._repo(bad)


def test_not_connected_points_at_the_vault(monkeypatch):
    from harness.vault.vault import VaultError
    with_vault(monkeypatch, {("POST", "/v1/search"): (VaultError("no credential for 'notion': add one first"), None)})
    out = run(tools(work_apps.make_notion_tools)["notion__search"].handler(query="roadmap"))
    assert out.startswith("NOTION_NOT_CONNECTED") and "/vault" in out


def test_notion_page_reads_as_text(monkeypatch):
    v = with_vault(monkeypatch, {
        ("GET", "/v1/pages/p1"): (200, {"url": "https://notion.so/p1", "properties": {"Name": {"type": "title", "title": [{"plain_text": "Roadmap"}]}}}),
        ("GET", "/v1/blocks/p1/children"): (200, {"results": [
            {"type": "heading_2", "heading_2": {"rich_text": [{"plain_text": "Q4"}]}},
            {"type": "to_do", "to_do": {"rich_text": [{"plain_text": "Ship voice"}], "checked": True}},
            {"type": "bulleted_list_item", "bulleted_list_item": {"rich_text": [{"plain_text": "Billing"}]}}]})})
    text = run(tools(work_apps.make_notion_tools)["notion__read_page"].handler(page_id="p1"))
    assert text.startswith("Roadmap — https://notion.so/p1") and "## Q4\n[x] Ship voice\n- Billing" in text
    assert v.calls[0]["headers"]["Notion-Version"] == work_apps.NOTION_VERSION


def test_slack_post_and_missing_scope(monkeypatch):
    v = with_vault(monkeypatch, {("POST", "/api/chat.postMessage"): (200, {"ok": True, "channel": "C1"}),
                                 ("GET", "/api/search.messages"): (200, {"ok": False, "error": "missing_scope"})})
    t = tools(work_apps.make_slack_tools)
    assert run(t["slack__send_message"].handler(channel_id="C1", text="Standup in 5")) == "Sent to C1."
    assert v.calls[0]["body"] == {"channel": "C1", "text": "Standup in 5"}
    assert "missing a permission" in run(t["slack__search_messages"].handler(query="budget"))


# -------------------------------------------------------- connect endpoint

class ConnectVault:
    def __init__(self, check_status):
        self.check_status, self.revoked, self.added, self.consented = check_status, [], [], []

    async def list_credentials(self, uid):
        return []

    async def add_credential(self, **kw):
        self.added.append(kw)
        return SimpleNamespace(id=5)

    async def grant_consent(self, **kw):
        self.consented.append(kw)

    async def call(self, **kw):
        return SimpleNamespace(status=self.check_status, body="{}")

    async def revoke_credential(self, uid, cid):
        self.revoked.append(cid)
        return True


def _client(monkeypatch, vault):
    import harness.vault as vault_mod
    monkeypatch.setattr(vault_mod, "current", lambda: vault)
    app = FastAPI()
    app.include_router(integ.router)
    app.dependency_overrides[get_current_user] = lambda: {"user_id": "7"}
    return TestClient(app)


def _offered(monkeypatch, *apps):
    """GitHub, Notion and Slack are hidden now; these tests check the connect flow itself."""
    import dataclasses

    from harness.connectors import registry
    for a in apps:
        monkeypatch.setitem(registry.BUILTIN, a, dataclasses.replace(registry.BUILTIN[a], hidden=False))


def test_a_working_token_is_kept_with_write_consent(monkeypatch):
    _offered(monkeypatch, "github")
    v = ConnectVault(200)
    r = _client(monkeypatch, v).post("/integrations/apps/github", json={"token": "github_pat_abcdefgh"})
    assert r.status_code == 200 and v.revoked == []
    assert v.added[0]["provider"] == "github" and v.consented[0]["allow_write"] is True


def test_a_refused_token_is_thrown_away(monkeypatch):
    _offered(monkeypatch, "slack")
    v = ConnectVault(401)
    r = _client(monkeypatch, v).post("/integrations/apps/slack", json={"token": "xoxp-wrongwrong"})
    assert r.status_code == 400 and "refused" in r.json()["detail"] and v.revoked == [5]


def test_hidden_work_apps_are_not_offered(monkeypatch):
    from harness.connectors import registry
    listed = {c["key"] for c in registry.available()}
    assert not {"github", "notion", "slack"} & listed
    assert {"gmail", "calendar"} <= listed
    v = ConnectVault(200)
    r = _client(monkeypatch, v).post("/integrations/apps/notion", json={"token": "ntn_abcdefghijkl"})
    assert r.status_code == 404 and "no longer offered" in r.json()["detail"] and v.added == []
    assert registry.BUILTIN["github"].tools is not None              # still accepted for old conversations


def test_auto_routing_never_switches_on_a_hidden_app(monkeypatch):
    import asyncio

    from harness.api.routes import integrations
    from harness.connectors import auto

    class NoGoogle:
        async def status(self, uid):
            return {"products": ["gmail"]}

    async def apps(uid):
        return {"github": True, "notion": True, "slack": True}

    monkeypatch.setattr("harness.integrations.google_oauth.google_tokens", lambda: NoGoogle())
    monkeypatch.setattr(integrations, "apps_status", apps)
    assert asyncio.run(auto.connected_apps("7")) == ["gmail"]


def test_unknown_app_is_404(monkeypatch):
    assert _client(monkeypatch, ConnectVault(200)).post("/integrations/apps/jira", json={"token": "12345678"}).status_code == 404


# ---------------------------------------------------------------- gating

def test_gates_by_name_and_pattern():
    assert gate_for("github__comment") == ("pro", "The GitHub connector")
    assert gate_for("travel_time")[0] == "plus" and gate_for("weather") is None
    assert not plan_allows_tool(PLANS["plus"], "generate_image") and plan_allows_tool(PLANS["pro"], "generate_image")
    assert plan_allows_tool(PLANS["plus"], "maps_search") and not plan_allows_tool(PLANS["free"], "maps_search")


def test_registry_gate_swaps_connector_tools_for_upgrade_cards(monkeypatch):
    from harness.tools.registry import ToolRegistry
    monkeypatch.setattr(entitlements, "billing_enabled", lambda: True)
    monkeypatch.setattr(billing_db, "get_account", lambda uid: Account(user_id=uid, plan="plus"))
    reg = ToolRegistry()
    for t in work_apps.make_slack_tools("7") + [maps.MAPS_SEARCH_TOOL]:
        reg.registry(t)
    run(entitlements.gate_registry("7", reg))
    out = run(reg.get("slack__send_message").handler(channel_id="C1", text="hi"))
    assert out.ui == {"kind": "upgrade", "feature": "The Slack connector", "plan": "pro", "plan_label": "Pro"}
    assert reg.get("maps_search") is maps.MAPS_SEARCH_TOOL           # Plus has maps
