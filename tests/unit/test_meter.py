"""The run meter (billing/meter.py): costs besides model tokens -- embeddings,
web searches, conversation summaries -- are charged to the user who caused
them, folded into the run's single charge, or settled on their own for uploads."""
import asyncio
import json
from decimal import Decimal
from types import SimpleNamespace

from harness.agent import context as ctx
from harness.billing import entitlements, meter
from harness.retrieval import embeddings
from harness.tools.builtin import web_search
from tests.unit.test_context_builder import _m


def run(coro):
    return asyncio.run(coro)


def test_costs_add_up_by_kind_and_nothing_happens_without_a_meter():
    meter.add(1.0, "web_search")                  # no meter open: ignored
    async def go():
        async with meter.metering("7") as m:
            meter.add(0.008, "web_search")
            meter.add(0.008, "web_search")
            meter.add(0.00002, "embeddings")
            await asyncio.to_thread(meter.add, 0.001, "summary")      # follows the run into threads
            return m
    m = run(go())
    assert m.extra == Decimal("0.01702")
    assert m.by_kind == {"web_search": Decimal("0.016"), "embeddings": Decimal("0.00002"), "summary": Decimal("0.001")}


def test_an_upload_settles_its_own_total(monkeypatch):
    charged = []
    monkeypatch.setattr(entitlements, "settle", lambda uid, cost, tid: charged.append((uid, cost)))
    async def go():
        async with meter.metering("7", settle_on_exit=True):
            embeddings._meter(SimpleNamespace(usage=SimpleNamespace(total_tokens=500_000)))
    run(go())
    assert charged == [("7", Decimal("0.01"))]          # 0.5M tokens at $0.02/M


def test_web_search_is_charged_only_when_it_ran(monkeypatch):
    class Vault:
        def __init__(self, status): self.status = status
        async def call(self, **kw):
            return SimpleNamespace(status=self.status, body=json.dumps({"results": [{"title": "t", "url": "u", "content": "c"}]}))
    async def go(status):
        monkeypatch.setattr(web_search, "current_vault", lambda: Vault(status))
        async with meter.metering("7") as m:
            await web_search.web_search("news")
            return m.extra
    assert run(go(200)) == Decimal("0.008")
    assert run(go(500)) == Decimal("0")


def test_summaries_use_the_cheap_model_and_are_metered(monkeypatch):
    bound = {}

    class Base:
        model = "gpt-5.5"
        def bound(self, model, effort):
            bound.update(model=model, effort=effort)
            return SimpleNamespace(model=model, chat=self.chat)
        async def chat(self, messages, tools):
            return SimpleNamespace(text="they agreed", input_tokens=10_000, output_tokens=500)
    monkeypatch.setattr("harness.providers.get_provider", lambda: Base())

    async def go():
        async with meter.metering("7") as m:
            out = await ctx.compact(prior_summary="", dropped=[_m(0, "user", "hi")])
            return out, m
    out, m = run(go())
    assert out == "they agreed"
    assert bound == {"model": "gpt-5.6-luna", "effort": "low"}                # never the expensive default
    assert m.by_kind["summary"] == Decimal(str(round(10_000 / 1e6 * 0.20 + 500 / 1e6 * 1.20, 8)))
