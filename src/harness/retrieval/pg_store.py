"""pgvector-backed document store -- the production replacement for the
JSON index in ``store.py`` and the in-process ``SessionVectorStore``.

Everything the agent can retrieve lives in one table (``document_chunks``):
the shared corpus as rows with ``user_id IS NULL``, each person's uploads as
rows carrying their subject id. A search is a single ANN query with the
ownership filter in the WHERE clause, so the isolation that used to depend on
a per-process dict is now a property of the query -- it survives a restart and
holds across replicas.

The SQLAlchemy engine is synchronous, so the async callers here hand the work
to a thread rather than blocking the event loop.
"""

import asyncio
import logging

from sqlalchemy import delete, func, select
from sqlalchemy import text as sql_text

from harness.db.base import SessionLocal
from harness.db.models import DocumentChunk

log = logging.getLogger(__name__)

# How many candidates HNSW inspects per query. Higher = better recall, slower.
# Must be >= the requested k; 64 is comfortable for the k<=10 we ask for.
HNSW_EF_SEARCH = 64


def _rows_to_hits(rows) -> list[dict]:
    # pgvector's cosine_distance is 1 - cosine_similarity; callers and the
    # old stores speak similarity, so convert once here.
    return [
        {"text": text, "source": source, "score": 1.0 - float(distance)}
        for text, source, distance in rows
    ]


def search_sync(
    query_embedding: list[float],
    *,
    user_id: str | None,
    k: int = 4,
    embed_model: str | None = None,
) -> list[dict]:
    """Nearest chunks for one owner. ``user_id=None`` searches the shared corpus.

    ``embed_model`` filters out rows embedded by a different model, which would
    otherwise be compared in a space they do not share.
    """
    stmt = (
        select(
            DocumentChunk.text,
            DocumentChunk.source,
            DocumentChunk.embedding.cosine_distance(query_embedding).label("distance"),
        )
        .where(DocumentChunk.user_id.is_(None) if user_id is None else DocumentChunk.user_id == user_id)
        .order_by("distance")
        .limit(k)
    )
    if embed_model:
        stmt = stmt.where(DocumentChunk.embed_model == embed_model)

    with SessionLocal() as session:
        # SET LOCAL would need an explicit transaction block; a plain SET on
        # this pooled connection is scoped to it and re-applied per query.
        session.execute(sql_text(f"SET hnsw.ef_search = {HNSW_EF_SEARCH:d}"))
        return _rows_to_hits(session.execute(stmt).all())


async def search(
    query_embedding: list[float],
    *,
    user_id: str | None,
    k: int = 4,
    embed_model: str | None = None,
) -> list[dict]:
    return await asyncio.to_thread(
        search_sync, query_embedding, user_id=user_id, k=k, embed_model=embed_model
    )


def add_chunks_sync(
    chunks: list[tuple[str, list[float]]],
    *,
    user_id: str | None,
    source: str,
    embed_model: str,
    index_version: str = "",
    replace_source: bool = True,
) -> int:
    """Insert one document's chunks. ``replace_source`` makes a re-upload of the
    same file name replace the previous copy instead of doubling it."""
    with SessionLocal() as session:
        if replace_source:
            session.execute(
                delete(DocumentChunk).where(
                    DocumentChunk.user_id.is_(None) if user_id is None else DocumentChunk.user_id == user_id,
                    DocumentChunk.source == source,
                )
            )
        session.add_all(
            DocumentChunk(
                user_id=user_id,
                source=source,
                chunk_index=i,
                text=text,
                embedding=embedding,
                embed_model=embed_model,
                index_version=index_version,
            )
            for i, (text, embedding) in enumerate(chunks)
        )
        session.commit()
        return len(chunks)


async def add_chunks(
    chunks: list[tuple[str, list[float]]],
    *,
    user_id: str | None,
    source: str,
    embed_model: str,
    index_version: str = "",
    replace_source: bool = True,
) -> int:
    return await asyncio.to_thread(
        add_chunks_sync,
        chunks,
        user_id=user_id,
        source=source,
        embed_model=embed_model,
        index_version=index_version,
        replace_source=replace_source,
    )


def replace_corpus_sync(
    rows: list[tuple[str, str, list[float]]],
    *,
    embed_model: str,
    index_version: str,
) -> int:
    """Swap the whole shared corpus (``user_id IS NULL``) in one transaction.

    ``rows`` is (source, text, embedding). The delete and the insert commit
    together, so a concurrent search sees either the old corpus or the new one,
    never an empty table halfway through a re-ingest.
    """
    with SessionLocal() as session:
        session.execute(delete(DocumentChunk).where(DocumentChunk.user_id.is_(None)))
        session.add_all(
            DocumentChunk(
                user_id=None,
                source=source,
                chunk_index=i,
                text=text,
                embedding=embedding,
                embed_model=embed_model,
                index_version=index_version,
            )
            for i, (source, text, embedding) in enumerate(rows)
        )
        session.commit()
        return len(rows)


def count_sync(user_id: str | None) -> int:
    with SessionLocal() as session:
        return int(
            session.execute(
                select(func.count(DocumentChunk.id)).where(
                    DocumentChunk.user_id.is_(None) if user_id is None else DocumentChunk.user_id == user_id
                )
            ).scalar_one()
        )


async def has_docs(user_id: str) -> bool:
    return await asyncio.to_thread(lambda: count_sync(user_id) > 0)


def clear_user_sync(user_id: str) -> int:
    with SessionLocal() as session:
        result = session.execute(delete(DocumentChunk).where(DocumentChunk.user_id == user_id))
        session.commit()
        return int(result.rowcount or 0)
