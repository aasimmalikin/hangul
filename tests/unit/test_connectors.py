"""Connectors: the registry, request validation, and the arXiv tools against
a canned Atom feed (no network)."""

import asyncio

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from harness.api.routes import ask as ask_route
from harness.api.routes import connectors as connectors_route
from harness.connectors import arxiv as arxiv_mod
from harness.connectors import available, tools_for, validate_keys
from harness.connectors.arxiv import make_arxiv_tools, parse_feed
from harness.tools.registry import ToolRegistry

FEED = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom" xmlns:arxiv="http://arxiv.org/schemas/atom">
  <entry>
    <id>http://arxiv.org/abs/2310.06825v1</id>
    <updated>2023-10-10T17:54:00Z</updated>
    <published>2023-10-10T17:54:00Z</published>
    <title>Mistral 7B</title>
    <summary>  We introduce Mistral 7B, a 7-billion-parameter language model
      engineered for superior performance.  </summary>
    <author><name>Albert Q. Jiang</name></author>
    <author><name>Alexandre Sablayrolles</name></author>
    <arxiv:doi>10.48550/arXiv.2310.06825</arxiv:doi>
    <link href="http://arxiv.org/abs/2310.06825v1" rel="alternate" type="text/html"/>
    <link title="pdf" href="http://arxiv.org/pdf/2310.06825v1" rel="related" type="application/pdf"/>
    <category term="cs.CL"/><category term="cs.AI"/>
  </entry>
</feed>"""


def run(coro):
    return asyncio.run(coro)


def test_parse_feed_extracts_the_fields_the_model_needs():
    (p,) = parse_feed(FEED)
    assert p["id"] == "2310.06825v1" and p["title"] == "Mistral 7B"
    assert p["authors"] == ["Albert Q. Jiang", "Alexandre Sablayrolles"]
    assert p["published"] == "2023-10-10" and p["categories"] == ["cs.CL", "cs.AI"]
    assert p["pdf"].endswith("2310.06825v1") and p["doi"].startswith("10.48550")
    assert "  " not in p["summary"]


def test_arxiv_tools_query_shape_rate_limit_and_errors(monkeypatch):
    monkeypatch.setattr(arxiv_mod, "MIN_INTERVAL_S", 0.0)
    seen: list[httpx.Request] = []
    status = {"code": 200}

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(req)
        return httpx.Response(status.get("code"), text=FEED if status["code"] == 200 else "nope")

    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    search, paper = make_arxiv_tools(http)

    out = run(search.handler(query="mixture of experts", max_results=50, sort="date", category="cs.CL"))
    q = seen[-1].url.params
    assert q["search_query"] == "(all:mixture of experts) AND cat:cs.CL"
    assert q["max_results"] == "10" and q["sortBy"] == "submittedDate"      # capped, mapped
    assert "[2310.06825v1] Mistral 7B" in out and "Albert Q. Jiang" in out

    run(search.handler(query="ti:attention AND au:vaswani"))
    assert seen[-1].url.params["search_query"] == "ti:attention AND au:vaswani"   # syntax passed through
    assert run(search.handler(query="   ")).startswith("ARXIV_ERROR")

    out = run(paper.handler(arxiv_id="https://arxiv.org/abs/2310.06825"))
    assert seen[-1].url.params["id_list"] == "2310.06825" and "Mistral 7B" in out
    assert run(paper.handler(arxiv_id="not an id")).startswith("ARXIV_ERROR")

    status["code"] = 503
    assert run(search.handler(query="x")).startswith("ARXIV_UNAVAILABLE")


def test_rate_limit_spaces_requests(monkeypatch):
    monkeypatch.setattr(arxiv_mod, "MIN_INTERVAL_S", 0.15)
    monkeypatch.setattr(arxiv_mod, "_last_call", 0.0)
    http = httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(200, text=FEED)))
    search, _ = make_arxiv_tools(http)

    async def two():
        loop = asyncio.get_running_loop()
        t0 = loop.time()
        await asyncio.gather(search.handler(query="a"), search.handler(query="b"))
        return loop.time() - t0

    assert run(two()) >= 0.14


def test_registry_and_validation():
    keys = {c["key"] for c in available()}
    assert "arxiv" in keys
    assert validate_keys(["arxiv", "arxiv"]) == ["arxiv"]
    with pytest.raises(ValueError, match="unknown connector"):
        validate_keys(["slack"])
    tools, note, tiers = tools_for(["arxiv"])
    assert sorted(t.name for t in tools) == ["arxiv_paper", "arxiv_search"]
    assert "arxiv_search" in note and tiers["arxiv_search"].value == "safe"
    assert tools_for([]) == ([], "", {})
    assert ask_route._policy.decide("arxiv_search").value == "allow"


def test_add_connector_tools_and_request_validation():
    reg = ToolRegistry()
    note = ask_route.add_connector_tools(reg, ["arxiv"])
    assert {t.name for t in reg.list()} == {"arxiv_search", "arxiv_paper"} and "Research connector" in note
    with pytest.raises(Exception) as ei:
        ask_route.connectors_or_422(["nope"])
    assert getattr(ei.value, "status_code", None) == 422
    assert ask_route.AskRequest(question="q", connectors=["arxiv"]).connectors == ["arxiv"]
    with pytest.raises(ValueError):
        ask_route.AskRequest(question="q", connectors=["a"] * 9)


def test_connectors_route_is_public():
    app = FastAPI()
    app.include_router(connectors_route.router)
    body = TestClient(app).get("/connectors").json()
    assert any(c["key"] == "arxiv" and c["label"] == "Research" and c["kind"] == "builtin" for c in body)
