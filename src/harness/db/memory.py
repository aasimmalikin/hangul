"""User Semantic memory: facts, preferences, corrections
Storage is in Postgres, but read in two ways:
profile_text(): a small always-loaded summary injected into the system prompt each run.
recall(): an on-demand tool the agent calls for a fuller lookup.
"""
from sqlalchemy import select
from harness.db.base import SessionLocal
from harness.db.models import UserMemory

# user_id arrives as the JWT ``sub`` (a string) but the column is the integer
# users.id, so every query casts at this boundary -- psycopg will not coerce.

def remember(user_id: str, content: str, kind: str = "preference") -> None:
    """Store a new memory for the user."""
    with SessionLocal() as session:
        session.add(UserMemory(user_id = int(user_id), content = content, kind = kind))
        session.commit()

def list_active(user_id: str)-> list[UserMemory]:
    """List all active memories for a user."""
    with SessionLocal() as session:
        rows = session.execute(select(UserMemory).where(UserMemory.user_id == int(user_id), UserMemory.active == True)
            .order_by(UserMemory.created_at.desc())).scalars().all()
        return list(rows)

def profile_text(user_id: str, limit: int = 12) -> str:
    """A compact profile block for the system prompt. Kept small on purpose --
    this is loaded on EVERY run, so it must not grow unbounded."""

    rows = list_active(user_id)[:limit]
    if not rows:
        return ""
    lines = [f"-{r.content}"for r in rows]
    return "What you know about this user:\n" + "\n".join(lines)

def deactivate_memory(user_id: str, memory_id: int)->None:
    """Deactivate a specific memory for a user."""
    with SessionLocal() as session:
        rows = session.get(UserMemory, memory_id)
        if rows and rows.user_id == int(user_id):
            rows.active = False
            session.commit()

    

