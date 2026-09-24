"""The conversation: a server-owned chat with a durable transcript.

Before this module, a conversation lived only in the browser tab
(``sessionStorage``) and was re-uploaded as ``AskRequest.history`` on every
request, so the agent saw a lossy text replay of earlier turns -- no tool
results -- and nothing could list, reopen or lock a chat. Here the
conversation is a row and its messages are rows, so many runs share one
context and a chat is resumable from any tab or device.

Everything here is sync SQLAlchemy (``SessionLocal``), matching
``db/episodes.py`` and ``db/memory.py``. Callers on the request path hand these
to ``asyncio.to_thread`` rather than blocking the event loop.

Ownership is a WHERE clause, never a post-hoc check -- the same structural
isolation ``make_search_docs_tool`` uses. ``user_id`` is the JWT ``sub`` as a
string (like ``threads.user_id``), NOT the integer ``users.id`` that
``episodes`` and ``user_memory`` key on.
"""

from uuid import uuid4

from sqlalchemy import select, update

from harness.db.base import SessionLocal
from harness.db.models import Conversation, ConversationMessage

# Roles we persist. A "system" message is rebuilt from the prompt template on
# every run (its version can change between turns), so it is never stored.
STORED_ROLES = frozenset({"user", "assistant", "tool"})

# Keys of an OpenAI message that are not role/content and so ride in `extra`.
_EXTRA_KEYS = ("tool_calls", "tool_call_id", "name", "ui")


def _estimate_tokens(text: str) -> int:
    """Rough token count. Deliberately not tiktoken: this only feeds a context
    budget that wants to be conservative, and an extra dependency (plus its
    per-model vocab download) is not worth the precision."""
    return max(1, len(text or "") // 4)


def create_conversation(
    user_id: str,
    *,
    title: str = "",
    model: str | None = None,
    effort: str | None = None,
    connectors: list[str] | tuple[str, ...] = (),
    mode: str = "default",
    docs_only: bool = False,
) -> str:
    """Start a conversation and return its id (``uuid4().hex``, 32 chars).

    32 hex rather than a dashed UUID on purpose: ``transactions.thread_id`` is
    String(32), and the ids in this system are all ``uuid4().hex``.
    """
    conv_id = uuid4().hex
    with SessionLocal() as session:
        session.add(Conversation(
            id = conv_id,
            user_id = user_id,
            title = title[:200],
            model = model,
            effort = effort,
            connectors = list(connectors),
            mode = mode,
            docs_only = docs_only,
        ))
        session.commit()
    return conv_id


def get_conversation(conversation_id: str, user_id: str) -> Conversation | None:
    """One conversation the caller owns, or None. Someone else's id and a
    missing id are indistinguishable so the route can answer 404 for both."""
    with SessionLocal() as session:
        return session.execute(
            select(Conversation).where(
                Conversation.id == conversation_id,
                Conversation.user_id == user_id,
                Conversation.active == True,
            )
        ).scalar_one_or_none()


def list_conversations(user_id: str, limit: int = 50) -> list[Conversation]:
    """This user's active conversations, most recently touched first."""
    with SessionLocal() as session:
        rows = session.execute(
            select(Conversation)
            .where(Conversation.user_id == user_id, Conversation.active == True)
            .order_by(Conversation.updated_at.desc())
            .limit(limit)
        ).scalars().all()
        return list(rows)


def append_messages(conversation_id: str, run_id: str, messages: list[dict]) -> int:
    """Append messages to the transcript; returns the new ``next_seq``.

    The sequence is allocated under ``SELECT ... FOR UPDATE`` on the
    conversation row, so two runs appending at once cannot produce two
    messages with the same seq (the unique constraint would reject the second
    anyway -- the lock is what makes it not happen). Runs in one conversation
    are already serialised by the claim in ``api/conversation_lock.py``; this
    holds even if that is bypassed.

    ``system`` messages are skipped: the system prompt is rebuilt per run.
    """
    rows = [m for m in messages if m.get("role") in STORED_ROLES]
    with SessionLocal() as session:
        conv = session.execute(
            select(Conversation).where(Conversation.id == conversation_id).with_for_update()
        ).scalar_one_or_none()
        if conv is None:
            return 0
        seq = conv.next_seq
        for m in rows:
            content = m.get("content") or ""
            if not isinstance(content, str):
                content = str(content)
            extra = {k: m[k] for k in _EXTRA_KEYS if m.get(k) is not None}
            session.add(ConversationMessage(
                conversation_id = conversation_id,
                seq = seq,
                role = m["role"],
                content = content,
                extra = extra,
                run_id = run_id,
                tokens = _estimate_tokens(content),
            ))
            seq += 1
        conv.next_seq = seq
        session.commit()
        return seq


def load_messages(conversation_id: str, after_seq: int = 0) -> list[ConversationMessage]:
    """The transcript in order. ``after_seq`` skips what a summary covers."""
    with SessionLocal() as session:
        rows = session.execute(
            select(ConversationMessage)
            .where(ConversationMessage.conversation_id == conversation_id,
                   ConversationMessage.seq >= after_seq)
            .order_by(ConversationMessage.seq)
        ).scalars().all()
        return list(rows)


def set_title(conversation_id: str, title: str) -> None:
    """Name the conversation from its first user message. Only fills an empty
    title, so a user's rename is never overwritten by a later turn."""
    with SessionLocal() as session:
        session.execute(
            update(Conversation)
            .where(Conversation.id == conversation_id, Conversation.title == "")
            .values(title = title[:200])
        )
        session.commit()


def rename_conversation(conversation_id: str, user_id: str, title: str) -> bool:
    with SessionLocal() as session:
        result = session.execute(
            update(Conversation)
            .where(Conversation.id == conversation_id, Conversation.user_id == user_id,
                   Conversation.active == True)
            .values(title = title[:200])
        )
        session.commit()
        return result.rowcount > 0


def set_summary(conversation_id: str, text: str, through_seq: int) -> None:
    """Store the rolling compaction of everything at or below ``through_seq``.
    Guarded by ``summary_through_seq <=``: a slow writer must not replace a
    newer summary with an older, shorter-reaching one."""
    with SessionLocal() as session:
        session.execute(
            update(Conversation)
            .where(Conversation.id == conversation_id,
                   Conversation.summary_through_seq <= through_seq)
            .values(summary_text = text, summary_through_seq = through_seq)
        )
        session.commit()


def save_security(conversation_id: str, snapshot: dict) -> None:
    """Persist the conversation's prompt-injection taint. Unlike the per-run
    copy on ``threads.security``, this is what makes a tainted chat still
    tainted on the next turn."""
    with SessionLocal() as session:
        session.execute(
            update(Conversation)
            .where(Conversation.id == conversation_id)
            .values(security = dict(snapshot or {}))
        )
        session.commit()


def bind_settings(conversation_id: str, *, model: str | None, effort: str | None,
                  connectors: list[str] | None, mode: str | None) -> None:
    """Record the settings the first run resolved, so a resume rebinds them.
    Only fills what is still unset; a later turn never rewrites them."""
    values: dict = {}
    with SessionLocal() as session:
        conv = session.get(Conversation, conversation_id)
        if conv is None:
            return
        if conv.model is None and model:
            values["model"] = model
        if conv.effort is None and effort:
            values["effort"] = effort
        if not conv.connectors and connectors:
            values["connectors"] = list(connectors)
        if mode and conv.mode == "default" and mode != "default":
            values["mode"] = mode
        if not values:
            return
        session.execute(update(Conversation).where(Conversation.id == conversation_id).values(**values))
        session.commit()


def deactivate_conversation(conversation_id: str, user_id: str) -> bool:
    """Hide a conversation. False when it does not exist, is already hidden, or
    belongs to someone else -- indistinguishable on purpose. Hide rather than
    delete, matching ``deactivate_episode``: the transcript stays for audit."""
    with SessionLocal() as session:
        result = session.execute(
            update(Conversation)
            .where(Conversation.id == conversation_id, Conversation.user_id == user_id,
                   Conversation.active == True)
            .values(active = False)
        )
        session.commit()
        return result.rowcount > 0


def message_counts(conversation_ids: list[str]) -> dict[str, int]:
    """Message count per conversation, for the rail. One query, not N."""
    if not conversation_ids:
        return {}
    from sqlalchemy import func
    with SessionLocal() as session:
        rows = session.execute(
            select(ConversationMessage.conversation_id, func.count())
            .where(ConversationMessage.conversation_id.in_(conversation_ids))
            .group_by(ConversationMessage.conversation_id)
        ).all()
        return {cid: n for cid, n in rows}
