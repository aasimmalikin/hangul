"""Factory for a per-user search_docs tool, backed by pgvector.

Searches the caller's uploaded documents first, falling back to the shared
corpus. Both live in ``document_chunks``; the user's rows carry their subject
id and the corpus rows carry NULL, so the isolation is the WHERE clause of a
single ANN query rather than a process-local index -- it survives a restart
and holds across replicas.
"""

import logging

from harness.retrieval import pg_store
from harness.retrieval.embeddings import get_embedder
from harness.tools.base import Tool

log = logging.getLogger(__name__)

DESCRIPTION = (
    "Search the user's document library for passages relevant to a "
    "query. This is the only way to reach that library -- the "
    "filesystem tools cannot see it. Use it for any question about "
    "what the documents say, including when the user names a "
    "document by title. Cite the [source] shown with each passage."
)

PARAMETERS = {
    "type": "object",
    "properties": {"query": {"type": "string"}, "k": {"type": "integer"}},
    "required": ["query"],
}

# k is the model's to choose, so bound it: an unbounded k would pull the whole
# corpus into the context window.
MAX_K = 10


def format_hits(hits: list[dict]) -> str:
    return "\n\n".join(f"[{h['source']}] {h['text']}" for h in hits)


def make_search_docs_tool(user_id: str) -> Tool:
    async def search_docs(query: str, k: int = 3) -> str:
        k = max(1, min(int(k), MAX_K))
        embedder = get_embedder()
        emb = await embedder.embed(query)

        try:
            # 1. the user's own uploads
            hits = await pg_store.search(emb, user_id=user_id, k=k, embed_model=embedder.model)
            if hits:
                return format_hits(hits)

            # 2. fall back to the shared corpus
            hits = await pg_store.search(emb, user_id=None, k=k, embed_model=embedder.model)
        except Exception:
            log.exception("search_docs: vector store query failed")
            return "The document index is temporarily unavailable. Answer without it, and say so."

        return format_hits(hits) if hits else "No documents available to search."

    return Tool(
        name="search_docs",
        description=DESCRIPTION,
        parameter=PARAMETERS,
        handler=search_docs,
    )
