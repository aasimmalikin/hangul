"""The shared-corpus search_docs (no per-user uploads); used by the eval
runner and the module-level registry. Per request, `make_search_docs_tool`
in `search_docs_session` is the one that gets wrapped in."""

from harness.retrieval import pg_store
from harness.retrieval.embeddings import get_embedder
from harness.tools.base import Tool
from harness.tools.builtin.search_docs_session import (
    DESCRIPTION,
    MAX_K,
    PARAMETERS,
    format_hits,
)


async def search_docs(query: str, k: int = 3) -> str:
    k = max(1, min(int(k), MAX_K))
    embedder = get_embedder()
    emb = await embedder.embed(query)
    hits = await pg_store.search(emb, user_id=None, k=k, embed_model=embedder.model)
    if not hits:
        return "No documents have been ingested yet."
    return format_hits(hits)


SEARCH_DOCS_TOOL = Tool(
    name = "search_docs",
    description = DESCRIPTION,
    parameter = PARAMETERS,
    handler = search_docs,
)
