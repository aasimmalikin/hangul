"""Episodic memory: past conversations summarized, embedded, and retrievable.

On thread close, a conversation is summarized into one 'episode', embedded, and
stored. Later, relevant episodes are retrieved by similarity to the current
question -- so the agent can recall 'what we discussed last week'.

The embed_model is stored per row: a future embedding-model change must not
silently misalign retrieval, so we can detect and re-embed stale rows.
"""
import asyncio

from openai import AsyncOpenAI
from sqlalchemy import select, text

from harness.config import get_settings
from harness.db.base import SessionLocal
from harness.db.models import Episode

EMBED_MODEL = "text-embedding-3-small"
_client = AsyncOpenAI(api_key=get_settings().openai_api_key)

async def _embed(content: str) -> list[float]:
    """Embed text using OpenAI's embedding API."""
    resp = await _client.embeddings.create(model = EMBED_MODEL, input = content)
    return resp.data[0].embedding

async def store_episode(user_id: str, thread_id: str, summary: str, title: str = "") -> int:
    """Store (or refresh) the episode for one conversation. A chat the user
    continues after leaving re-summarises into the same row, keyed by
    (user_id, thread_id), so the Chats rail shows each conversation once.
    Returns the episode id."""
    vec = await _embed(summary)

    def _write() -> int:
        with SessionLocal() as session:
            row = session.execute(
                select(Episode).where(Episode.user_id == int(user_id), Episode.thread_id == thread_id)
            ).scalar_one_or_none()
            if row is None:
                row = Episode(user_id = int(user_id), thread_id = thread_id)
                session.add(row)
            row.title = title[:200]
            row.summary = summary[:2048]
            row.embedding = vec
            row.embed_model = EMBED_MODEL
            row.active = True
            session.commit()
            return row.id

    # SessionLocal is sync SQLAlchemy; run it in a worker thread so the
    # remote round-trip does not block the event loop.
    return await asyncio.to_thread(_write)

def list_episodes(user_id: str) -> list[Episode]:
    """Active conversations for a user, most recently touched first."""
    with SessionLocal() as session:
        rows = session.execute(
            select(Episode).where(Episode.user_id == int(user_id), Episode.active == True)
            .order_by(Episode.updated_at.desc())
        ).scalars().all()
        return list(rows)

def deactivate_episode(user_id: str, episode_id: int) -> bool:
    """Hide one conversation. False when it does not exist, is already
    hidden, or belongs to someone else -- indistinguishable on purpose."""
    with SessionLocal() as session:
        row = session.get(Episode, episode_id)
        if row is None or row.user_id != int(user_id) or not row.active:
            return False
        row.active = False
        session.commit()
        return True

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
                    WHERE user_id = :uid AND active
                    ORDER BY (embedding <=> CAST(:qvec AS vector)) + (EXTRACT (EPOCH FROM (now() - created_at)) / 2592000.0)*0.1 LIMIT :lim """),
                {"uid": int(user_id), "qvec": str(qvec), "lim": limit},
            ).fetchall()
            return [row[0] for row in rows]

    return await asyncio.to_thread(_query)