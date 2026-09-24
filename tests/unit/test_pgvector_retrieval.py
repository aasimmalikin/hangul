"""Retrieval now lives in pgvector (`document_chunks`).

These run against a fake for `pg_store` -- no Postgres, like the other unit
tests. What they pin down is the part that is easy to get wrong and expensive
to notice: that a search only ever sees its own owner's rows, that the shared
corpus is the fallback and not the first stop, and that a retrieval outage
degrades instead of killing the run.
"""
import asyncio
from types import SimpleNamespace

import pytest

from harness.retrieval import pg_store
from harness.tools.builtin import search_docs as shared_tool
from harness.tools.builtin import search_docs_session as session_tool
from harness.tools.builtin.search_docs_session import MAX_K, make_search_docs_tool


class _FakeStore:
    """Stands in for the pgvector queries: rows keyed by owner."""

    def __init__(self, rows):
        self.rows = rows          # {user_id or None: [(source, text)]}
        self.calls = []           # (user_id, k) in order

    async def search(self, _emb, *, user_id, k=4, embed_model=None):
        self.calls.append((user_id, k))
        return [
            {"source": s, "text": t, "score": 0.9}
            for s, t in self.rows.get(user_id, [])
        ][:k]


@pytest.fixture
def store(monkeypatch):
    fake = _FakeStore({
        "7": [("notes.txt", "seven's own upload")],
        None: [("corpus.txt", "the shared corpus")],
    })
    monkeypatch.setattr(pg_store, "search", fake.search)
    # both tool modules bind get_embedder at import time, so patch it where it
    # is used, not where it is defined -- otherwise these tests quietly bill a
    # real embeddings call.
    embedder = SimpleNamespace(model="text-embedding-3-small", embed=_embed)
    for module in (shared_tool, session_tool):
        monkeypatch.setattr(module, "get_embedder", lambda: embedder)
    return fake


async def _embed(_text):
    return [0.1] * 1536


def _run(coro):
    return asyncio.run(coro)


def test_user_sees_only_their_own_rows(store):
    answer = _run(make_search_docs_tool("7").handler(query="what do my notes say?"))
    assert "seven's own upload" in answer
    assert "shared corpus" not in answer
    # the user's own rows are queried first, and the corpus is never reached
    assert store.calls == [("7", 3)]


def test_falls_back_to_shared_corpus_when_user_has_no_uploads(store):
    answer = _run(make_search_docs_tool("99").handler(query="anything"))
    assert "the shared corpus" in answer
    assert store.calls == [("99", 3), (None, 3)]


def test_k_is_clamped(store):
    _run(make_search_docs_tool("7").handler(query="q", k=500))
    assert store.calls[0][1] == MAX_K


def test_retrieval_outage_degrades_instead_of_failing(monkeypatch, store):
    async def boom(*_a, **_k):
        raise RuntimeError("connection refused")

    monkeypatch.setattr(pg_store, "search", boom)
    answer = _run(make_search_docs_tool("7").handler(query="q"))
    assert "temporarily unavailable" in answer


def test_shared_tool_never_queries_a_user(store):
    answer = _run(shared_tool.search_docs(query="q"))
    assert "the shared corpus" in answer
    assert store.calls == [(None, 3)]


def test_empty_corpus_says_so(monkeypatch, store):
    monkeypatch.setattr(pg_store, "search", _FakeStore({}).search)
    assert "No documents" in _run(shared_tool.search_docs(query="q"))
