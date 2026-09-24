"""The token vault: secrets are encrypted at rest, the agent and MCP servers
only ever hold short-lived grants, the proxy injects the real credential and
redacts it from everything that comes back or gets logged.

In-memory stores + httpx.MockTransport: no Postgres, Redis or network."""

import asyncio
import json
from datetime import timedelta

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from harness.api.auth import get_current_user
from harness.api.routes import vault as vault_routes
from harness.mcp.client import MCPClient
from harness.mcp.config import ServerConfig, has_vault_refs, server_config_from_dict
from harness.policy.audit import AuditLog
from harness.tools.builtin import vault_request as vr
from harness.tools.builtin import web_search as ws
from harness.vault import set_current
from harness.vault.crypto import FernetCipher, fingerprint, generate_master_key
from harness.vault.grants import GrantError, InMemoryGrantStore
from harness.vault.policy import GrantScope, VaultPolicy
from harness.vault.providers import BUILTIN, generic_spec
from harness.vault.proxy import ProxyError
from harness.vault.redact import Redactor
from harness.vault.store import InMemoryConsentStore, InMemoryCredentialStore
from harness.vault.vault import SYSTEM, Vault, VaultError

SECRET = "ghp_ThisIsAVeryLongSecretToken1234567890"
TAVILY = "tvly-operator-key-0000000000"


def run(coro):
    return asyncio.run(coro)


class Upstream:
    """Fake third-party API: records what it received, echoes headers back
    (so a leaked credential in the body would be visible), can set cookies."""
    def __init__(self):
        self.calls: list[httpx.Request] = []
        self.status = 200
        self.body: dict | None = None

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.calls.append(request)
        body = self.body or {"echo_auth": request.headers.get("authorization", ""),
                             "url": str(request.url), "n": len(self.calls)}
        return httpx.Response(self.status, json=body, headers={"Set-Cookie": "sid=1", "ETag": "x"})


def make_vault(*, audit=None, redactor=None, ttl=300, **kw):
    up = Upstream()
    v = Vault(
        cipher=FernetCipher(generate_master_key()),
        credentials=InMemoryCredentialStore(), consents=InMemoryConsentStore(),
        grants=InMemoryGrantStore(), redactor=redactor or Redactor(),
        http=httpx.AsyncClient(transport=httpx.MockTransport(up.handler)),
        grant_ttl_s=ttl, audit=audit, public_url="http://api.test:8000", **kw,
    )
    return v, up


# ------------------------------------------------------------------ crypto

def test_cipher_roundtrip_and_wrong_key():
    k1, k2 = generate_master_key(), generate_master_key()
    ct = FernetCipher(k1).encrypt(SECRET)
    assert ct != SECRET and SECRET not in ct
    assert FernetCipher(k1).decrypt(ct) == SECRET
    with pytest.raises(ValueError):
        FernetCipher(k2).decrypt(ct)
    with pytest.raises(ValueError):
        FernetCipher("not-a-key")


def test_fingerprint_is_stable_short_and_not_the_secret():
    assert fingerprint(SECRET) == fingerprint(SECRET)
    assert len(fingerprint(SECRET)) == 12 and fingerprint(SECRET) not in SECRET


# --------------------------------------------------------------- redaction

def test_redactor_scrubs_nested_and_ignores_short_values():
    r = Redactor()
    r.register(SECRET, "github")
    r.register("abc", "tiny")          # too short: never registered
    out = r.scrub({"a": f"token={SECRET}", "b": [SECRET, 1], "c": "abc"})
    assert SECRET not in json.dumps(out)
    assert out["a"].startswith("token=[REDACTED:github:")
    assert out["c"] == "abc"
    assert len(r) == 1


# ----------------------------------------------------------------- policy

def test_policy_host_method_path_body_and_budget():
    pol = VaultPolicy(max_body_bytes=10)
    gh = BUILTIN["github"]
    ro = GrantScope(provider="github", access="read", subject="7")
    assert pol.check(ro, gh, "GET", "/user").allowed
    assert "read-only" in pol.check(ro, gh, "POST", "/user").reason
    assert pol.check(GrantScope("github", "write", "7"), gh, "POST", "/user").allowed
    # a search POST is a read for tavily, so a read-only grant may make it
    assert pol.check(GrantScope("tavily", "read", "7"), BUILTIN["tavily"], "POST", "/search").allowed
    assert "grant is for" in pol.check(ro, BUILTIN["tavily"], "GET", "/x").reason
    assert "relative" in pol.check(ro, gh, "GET", "https://evil/x").reason
    assert "relative" in pol.check(ro, gh, "GET", "/../x").reason
    assert "exceeds" in pol.check(ro, gh, "GET", "/user", body_len=11).reason
    assert "exhausted" in pol.check(ro, gh, "GET", "/user", calls_left=0).reason
    assert "not allowed" in pol.check(GrantScope("tavily", "read", "7"), BUILTIN["tavily"], "GET", "/admin").reason


def test_classify_treats_tavily_search_post_as_read():
    assert BUILTIN["tavily"].classify("POST", "/search") == "read"
    assert BUILTIN["github"].classify("POST", "/repos") == "write"
    assert BUILTIN["github"].classify("get", "/repos") == "read"


def test_generic_spec_is_per_host():
    s = generic_spec("https://api.example.com/v1")
    assert s.name == "http:api.example.com" and s.base_url == "https://api.example.com"
    with pytest.raises(ValueError):
        generic_spec("ftp://nope")


# ----------------------------------------------------------------- grants

def test_grant_lifecycle():
    async def scenario():
        store = InMemoryGrantStore()
        scope = GrantScope("github", "read", "7", "t1")
        token, grant = await store.mint(1, scope, ttl_s=60, max_calls=2)
        assert token.startswith("vg_") and grant.token_hash != token
        assert token not in json.dumps([g.as_json() for g in store._d.values()])
        assert (await store.lookup(token)).calls_left == 2
        await store.consume(grant); await store.consume(grant)
        with pytest.raises(GrantError, match="exhausted"):
            await store.consume(grant)
        await store.revoke(token)
        with pytest.raises(GrantError):
            await store.lookup(token)
        with pytest.raises(GrantError, match="malformed"):
            await store.lookup("nope")
        t2, _ = await store.mint(1, scope, ttl_s=-1, max_calls=1)
        with pytest.raises(GrantError, match="expired"):
            await store.lookup(t2)
    run(scenario())


# ------------------------------------------------------------------ vault

def test_add_credential_encrypts_dedups_and_registers_for_redaction():
    async def scenario():
        v, _ = make_vault()
        c1 = await v.add_credential(user_id="7", provider="github", secret=SECRET, label="pat")
        c2 = await v.add_credential(user_id="7", provider="github", secret=SECRET)
        assert c1.id == c2.id                       # same fingerprint -> same row
        assert SECRET not in c1.ciphertext and "ciphertext" not in c1.public()
        assert v.redactor.scrub_text(SECRET) != SECRET
        with pytest.raises(VaultError):
            await v.add_credential(user_id="7", provider="nope", secret=SECRET)
        with pytest.raises(VaultError):
            await v.add_credential(user_id="7", provider="github", secret="short")
    run(scenario())


def test_consent_gates_grants_and_writes():
    async def scenario():
        v, _ = make_vault()
        await v.add_credential(user_id="7", provider="github", secret=SECRET)
        with pytest.raises(VaultError, match="VAULT_CONSENT_REQUIRED"):
            await v.mint_grant(subject="7", provider="github")
        with pytest.raises(VaultError, match="no credential"):
            await v.grant_consent(user_id="8", provider="github", ttl=timedelta(hours=1))
        c = await v.grant_consent(user_id="7", provider="github", ttl=timedelta(hours=1))
        _, grant = await v.mint_grant(subject="7", provider="github", thread_id="t1")
        assert grant.scope.access == "read" and grant.scope.thread_id == "t1"
        with pytest.raises(VaultError, match="read-only"):
            await v.mint_grant(subject="7", provider="github", write=True)
        await v.revoke_consent("7", c.id)
        with pytest.raises(VaultError, match="VAULT_CONSENT_REQUIRED"):
            await v.mint_grant(subject="7", provider="github")
        assert (await v.consented_providers("7")) == {}
    run(scenario())


def test_system_credential_auto_consent_and_isolation():
    async def scenario():
        v, _ = make_vault()
        await v.add_credential(user_id=None, provider="tavily", secret=TAVILY)
        await v.add_credential(user_id=None, provider="github", secret=SECRET)
        # tavily: operator key usable by any user without a consent row
        await v.mint_grant(subject="7", provider="tavily")
        assert (await v.consented_providers("7")) == {"tavily": False}
        # github system key still needs consent
        with pytest.raises(VaultError, match="VAULT_CONSENT_REQUIRED"):
            await v.mint_grant(subject="7", provider="github")
        # the system subject may use system credentials without consent
        await v.mint_grant(subject=SYSTEM, provider="github")
        # but never a user's own
        await v.add_credential(user_id="9", provider="http:x.test", secret=SECRET, base_url="https://x.test")
        with pytest.raises(VaultError, match="no credential"):
            await v.mint_grant(subject=SYSTEM, provider="http:x.test")
    run(scenario())


def test_revoking_credential_kills_grants_and_consents():
    async def scenario():
        v, _ = make_vault()
        c = await v.add_credential(user_id="7", provider="github", secret=SECRET)
        await v.grant_consent(user_id="7", provider="github", ttl=timedelta(hours=1))
        token, _ = await v.mint_grant(subject="7", provider="github")
        assert await v.revoke_credential("7", c.id)
        assert not await v.revoke_credential("7", c.id)          # idempotent -> 404 upstairs
        assert not await v.revoke_credential("8", c.id)
        with pytest.raises(ProxyError) as ei:
            await v.proxy(token, method="GET", path="/user")
        assert ei.value.status == 401
        assert (await v.list_consents("7"))[0].revoked_at is not None
    run(scenario())


# ------------------------------------------------------------------ proxy

def test_proxy_injects_strips_and_redacts():
    async def scenario():
        audit_lines = []

        class FakeAudit:
            def record_vault(self, **f): audit_lines.append(f)

        v, up = make_vault(audit=FakeAudit())
        await v.add_credential(user_id="7", provider="github", secret=SECRET)
        await v.grant_consent(user_id="7", provider="github", ttl=timedelta(hours=1))
        token, _ = await v.mint_grant(subject="7", provider="github", thread_id="t1")
        r = await v.proxy(token, method="GET", path="/user/repos",
                          headers={"Authorization": "Bearer attacker", "Cookie": "x", "Accept": "application/vnd.github+json"},
                          query={"per_page": "2"})
        sent = up.calls[0]
        assert sent.headers["authorization"] == f"Bearer {SECRET}"      # injected, caller's dropped
        assert "cookie" not in sent.headers
        assert str(sent.url) == "https://api.github.com/user/repos?per_page=2"
        assert r.status == 200
        body = json.loads(r.body)
        assert SECRET not in r.body and body["echo_auth"].startswith("Bearer [REDACTED:github:")
        assert "set-cookie" not in {k.lower() for k in r.headers} and r.headers.get("etag") == "x"
        assert audit_lines[-1]["provider"] == "github" and audit_lines[-1]["subject"] == "7"
        assert SECRET not in json.dumps(audit_lines) and token not in json.dumps(audit_lines)
    run(scenario())


def test_proxy_enforces_grant_scope_budget_and_lifetime():
    async def scenario():
        v, up = make_vault()
        await v.add_credential(user_id="7", provider="github", secret=SECRET)
        await v.grant_consent(user_id="7", provider="github", ttl=timedelta(hours=1), allow_write=True)
        token, _ = await v.mint_grant(subject="7", provider="github")   # read-only grant
        with pytest.raises(ProxyError) as ei:
            await v.proxy(token, method="DELETE", path="/repos/a/b")
        assert ei.value.status == 403 and not up.calls
        wt, _ = await v.mint_grant(subject="7", provider="github", write=True)
        assert (await v.proxy(wt, method="DELETE", path="/repos/a/b")).status == 200
        with pytest.raises(ProxyError) as ei:
            await v.proxy("vg_bogus", method="GET", path="/user")
        assert ei.value.status == 401
        # budget: max_calls_per_grant for github is 50
        for _ in range(49):
            await v.proxy(wt, method="GET", path="/user")
        with pytest.raises(ProxyError, match="exhausted"):
            await v.proxy(wt, method="GET", path="/user")
    run(scenario())


def test_proxy_upstream_failure_is_502_and_body_is_capped():
    async def scenario():
        def boom(request):
            raise httpx.ConnectError("nope")
        v = Vault(cipher=FernetCipher(generate_master_key()), credentials=InMemoryCredentialStore(),
                  consents=InMemoryConsentStore(), grants=InMemoryGrantStore(), redactor=Redactor(),
                  http=httpx.AsyncClient(transport=httpx.MockTransport(boom)))
        await v.add_credential(user_id=None, provider="github", secret=SECRET)
        with pytest.raises(ProxyError) as ei:
            await v.call(subject=SYSTEM, provider="github", method="GET", path="/user")
        assert ei.value.status == 502 and "nope" not in ei.value.detail

        v2, up = make_vault(max_body_bytes=20)
        up.body = {"big": "x" * 100}
        await v2.add_credential(user_id=None, provider="github", secret=SECRET)
        r = await v2.call(subject=SYSTEM, provider="github", method="GET", path="/user")
        assert r.truncated and len(r.body) == 20
    run(scenario())


def test_call_mints_one_off_grant_and_revokes_it():
    async def scenario():
        v, up = make_vault()
        await v.add_credential(user_id=None, provider="tavily", secret=TAVILY)
        r = await v.call(subject="7", provider="tavily", method="POST", path="/search", body='{"query":"x"}')
        assert r.status == 200 and up.calls[0].headers["authorization"] == f"Bearer {TAVILY}"
        assert v.grants._d == {}                                  # nothing left behind
    run(scenario())


# ------------------------------------------------------------------ tools

def test_vault_tools_end_to_end(monkeypatch):
    async def scenario():
        v, up = make_vault()
        set_current(v)
        try:
            tools = {t.name: t for t in await vr.build_vault_tools("7", "t1")}
            assert "not connected any provider" in tools["vault_request"].description
            out = await tools["vault_request"].handler(provider="github", path="/user")
            assert out.startswith("VAULT_CONSENT_REQUIRED")     # no credential/consent yet

            await v.add_credential(user_id="7", provider="github", secret=SECRET)
            await v.grant_consent(user_id="7", provider="github", ttl=timedelta(hours=1))
            tools = {t.name: t for t in await vr.build_vault_tools("7", "t1")}
            assert "github" in tools["vault_request"].description
            out = await tools["vault_request"].handler(provider="github", path="user", query={"n": 1})
            assert out.startswith("HTTP 200") and SECRET not in out
            assert str(up.calls[-1].url) == "https://api.github.com/user?n=1"

            out = await tools["vault_mutate"].handler(provider="github", method="GET", path="/x")
            assert out.startswith("VAULT_DENIED")
            out = await tools["vault_mutate"].handler(provider="github", method="POST", path="/x", body={"a": 1})
            assert out.startswith("VAULT_CONSENT_REQUIRED") and "read-only" in out
            await v.grant_consent(user_id="7", provider="github", ttl=timedelta(hours=1), allow_write=True)
            out = await tools["vault_mutate"].handler(provider="github", method="POST", path="/x", body={"a": 1})
            assert out.startswith("HTTP 200") and up.calls[-1].content == b'{"a": 1}'
        finally:
            set_current(None)
        out = await tools["vault_request"].handler(provider="github", path="/user")
        assert out.startswith("VAULT_UNAVAILABLE")
    run(scenario())


def test_web_search_goes_through_the_vault():
    async def scenario():
        v, up = make_vault()
        up.body = {"results": [{"title": "T", "url": "http://u", "content": "C"}]}
        set_current(v)
        try:
            assert "WEB_SEARCH_UNAVAILABLE" in await ws.web_search("q")   # no tavily credential yet
            await v.add_credential(user_id=None, provider="tavily", secret=TAVILY)
            out = await ws.web_search("q", max_results=2)
            assert out == "[T] (http://u)\nC"
            req = up.calls[-1]
            assert str(req.url) == "https://api.tavily.com/search"
            assert req.headers["authorization"] == f"Bearer {TAVILY}"
            assert json.loads(req.content) == {"query": "q", "max_results": 2}
        finally:
            set_current(None)
        assert "WEB_SEARCH_UNAVAILABLE" in await ws.web_search("q")
    run(scenario())


def test_audit_log_scrubs_secrets(tmp_path):
    from harness.vault.redact import redactor as global_redactor
    global_redactor.register(SECRET, "github")
    try:
        a = AuditLog(str(tmp_path / "audit.jsonl"))
        a.record(tool="x", args={"token": SECRET}, decision="allow", tier="safe")
        a.record_vault(subject="7", provider="github", method="GET", path="/u", status=200, ms=3)
        text = (tmp_path / "audit.jsonl").read_text()
        assert SECRET not in text and "[REDACTED:github:" in text
        assert a.vault_entries("7") and a.vault_entries("8") == []
    finally:
        global_redactor.forget(SECRET)


# -------------------------------------------------------------------- MCP

def test_mcp_config_vault_refs_and_raw_secret_warning(caplog):
    cfg = server_config_from_dict({"name": "gh", "command": "x",
                                   "env": {"GITHUB_TOKEN": "vault:github", "GITHUB_API_URL": "vault-proxy:github"}})
    assert has_vault_refs(cfg)
    assert not has_vault_refs(ServerConfig(name="a", command="x", env={"A": "b"}))
    with caplog.at_level("WARNING"):
        server_config_from_dict({"name": "raw", "command": "x", "env": {"API_TOKEN": "${SOME_TOKEN}"}})
    assert any("vault:<provider>" in r.message for r in caplog.records)


def test_mcp_client_resolves_refs_to_grants_and_revokes_on_close():
    async def scenario():
        v, _ = make_vault()
        await v.add_credential(user_id=None, provider="github", secret=SECRET)
        set_current(v)
        try:
            cfg = ServerConfig(name="gh", command="x",
                               env={"GITHUB_TOKEN": "vault:github", "GITHUB_API_URL": "vault-proxy:github", "PLAIN": "1"},
                               headers={"Authorization": "Bearer vault:github"})
            client = MCPClient(cfg)
            resolved = await client._resolved_config()
            assert resolved.env["GITHUB_TOKEN"].startswith("vg_") and SECRET not in json.dumps(resolved.env)
            assert resolved.env["GITHUB_API_URL"] == "http://api.test:8000/vault/proxy/github/"
            assert resolved.env["PLAIN"] == "1"
            assert resolved.headers["Authorization"].startswith("Bearer vg_")
            assert len(client._grants) == 2 and len(v.grants._d) == 2
            # the grant works against the proxy, with the system subject
            r = await v.proxy(resolved.env["GITHUB_TOKEN"], method="GET", path="/user")
            assert r.status == 200
            await client._revoke_grants()
            assert v.grants._d == {} and client._grants == []
            # vault disabled -> a config with refs cannot connect
            set_current(None)
            with pytest.raises(ConnectionError, match="vault is disabled"):
                await MCPClient(cfg)._resolved_config()
        finally:
            set_current(None)
    run(scenario())


# ------------------------------------------------------------------ routes

def _app(v, user_id="7"):
    set_current(v)
    app = FastAPI()
    app.include_router(vault_routes.router)
    app.dependency_overrides[get_current_user] = lambda: {"user_id": user_id, "role": "user"}
    return TestClient(app)


def test_routes_never_return_secrets_and_scope_to_user():
    v, _ = make_vault()
    c = _app(v)
    try:
        assert c.get("/vault/providers").status_code == 200
        r = c.post("/vault/credentials", json={"provider": "github", "secret": SECRET, "label": "pat"})
        assert r.status_code == 201
        cred = r.json()
        assert SECRET not in r.text and "ciphertext" not in cred and cred["fingerprint"] == fingerprint(SECRET)
        assert c.post("/vault/credentials", json={"provider": "nope", "secret": SECRET}).status_code == 422
        assert [x["id"] for x in c.get("/vault/credentials").json()] == [cred["id"]]

        r = c.post("/vault/consents", json={"provider": "github", "ttl_hours": 2})
        assert r.status_code == 201 and r.json()["allow_write"] is False
        assert c.post("/vault/consents", json={"provider": "github", "ttl_hours": 0}).status_code == 422

        other = _app(v, user_id="8")
        assert other.get("/vault/credentials").json() == []
        assert other.delete(f"/vault/credentials/{cred['id']}").status_code == 404
        assert other.delete(f"/vault/consents/{r.json()['id']}").status_code == 404

        assert c.delete(f"/vault/consents/{r.json()['id']}").json() == {"revoked": r.json()["id"]}
        assert c.delete(f"/vault/credentials/{cred['id']}").json() == {"revoked": cred["id"]}
        assert c.delete(f"/vault/credentials/{cred['id']}").status_code == 404
    finally:
        set_current(None)


def test_proxy_routes_use_grant_not_jwt():
    async def prep():
        v, up = make_vault()
        await v.add_credential(user_id="7", provider="github", secret=SECRET)
        await v.grant_consent(user_id="7", provider="github", ttl=timedelta(hours=1))
        token, _ = await v.mint_grant(subject="7", provider="github")
        return v, up, token
    v, up, token = run(prep())
    app = FastAPI()
    app.include_router(vault_routes.router)      # no auth override: JWT dependency would 403 without a header
    c = TestClient(app)
    set_current(v)
    try:
        r = c.post("/vault/proxy", json={"grant": token, "method": "GET", "path": "/user", "query": {"a": "1"}})
        assert r.status_code == 200 and r.json()["status"] == 200 and SECRET not in r.text
        assert str(up.calls[-1].url) == "https://api.github.com/user?a=1"
        assert c.post("/vault/proxy", json={"grant": "vg_nope_nope_nope", "method": "GET", "path": "/user"}).status_code == 401
        assert c.post("/vault/proxy", json={"grant": token, "method": "DELETE", "path": "/user"}).status_code == 403

        # transparent form, as a stock MCP server with a base-url override would call it
        r = c.get("/vault/proxy/github/repos/a/b?x=1", headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 200 and str(up.calls[-1].url) == "https://api.github.com/repos/a/b?x=1"
        assert SECRET not in r.text and "set-cookie" not in r.headers
        assert c.get("/vault/proxy/github/user").status_code == 401
        assert c.get("/vault/credentials").status_code in (401, 403)   # JWT still required elsewhere
    finally:
        set_current(None)


def test_routes_503_when_vault_disabled():
    set_current(None)
    app = FastAPI()
    app.include_router(vault_routes.router)
    app.dependency_overrides[get_current_user] = lambda: {"user_id": "7", "role": "user"}
    assert TestClient(app).get("/vault/credentials").status_code == 503
