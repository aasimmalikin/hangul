"""Episodic memory: past conversations summarized, embedded, and retrievable.

On thread close, a conversation is summarized into one 'episode', embedded, and
stored. Later, relevant episodes are retrieved by similarity to the current
question -- so the agent can recall 'what we discussed last week'.

The embed_model is stored per row: a future embedding-model change must not
silently misalign retrieval, so we can detect and re-embed stale rows.
"""
import asyncio

from openai import AsyncOpenAI
from sqlalchemy import text

from harness.config import get_settings
from harness.db.base import SessionLocal
from harness.db.models import Episode

EMBED_MODEL = "text-embedding-3-small"
_client = AsyncOpenAI(api_key=get_settings().openai_api_key)

async def _embed(content: str) -> list[float]:
    """Embed text using OpenAI's embedding API."""
    resp = await _client.embeddings.create(model = EMBED_MODEL, input = content)
    return resp.data[0].embedding

async def store_episode(user_id: str, thread_id: str, summary: str) -> None:
    """Store a summarized conversation as an episode in the database."""
    vec = await _embed(summary)

    def _write() -> None:
        with SessionLocal() as session:
            session.add(Episode(
                user_id = int(user_id),
                thread_id = thread_id,
                summary = summary,
                embedding = vec,
                embed_model = EMBED_MODEL,
            ))
            session.commit()

    # SessionLocal is sync SQLAlchemy; run it in a worker thread so the
    # remote round-trip does not block the event loop.
    await asyncio.to_thread(_write)

async def recall_episodes(user_id: str, query: str, limit: int = 5) -> list[str]:
    """Return summaries of the most relevant episodes for a given query."""

    """Cosine distance (<=>) with a mild recency bias: newer episodes are nudged
    up, so 'what did we decide recently' favours recent context."""

    qvec = await _embed(query)

    def _query() -> list[str]:
        with SessionLocal() as session:
            rows = session.execute(
                text("""
                    SELECT summary
                    FROM episodes
                    WHERE user_id = :uid
                    ORDER BY (embedding <=> CAST(:qvec AS vector)) + (EXTRACT (EPOCH FROM (now() - created_at)) / 2592000.0)*0.1 LIMIT :lim """),
                {"uid": int(user_id), "qvec": str(qvec), "lim": limit},
            ).fetchall()
            return [row[0] for row in rows]

    return await asyncio.to_thread(_query)