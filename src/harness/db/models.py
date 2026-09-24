from datetime import datetime
from sqlalchemy import Boolean, Index, UniqueConstraint, DateTime, Integer, String, Text, func
from sqlalchemy import Numeric
from decimal import Decimal
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from harness.db.base import Base
from pgvector.sqlalchemy import Vector

# Dimensionality of the embedding model (text-embedding-3-small). Changing it
# means a migration plus a full re-ingest, so it lives here as one constant.
EMBED_DIM = 1536

class Thread(Base):
    __tablename__ = "threads"

    thread_id: Mapped[str] = mapped_column(String(64), primary_key = True)
    message: Mapped[list] = mapped_column(JSONB, nullable = False, default = list)
    step: Mapped[int] = mapped_column(Integer, nullable = False, default = 0)
    status: Mapped[str] = mapped_column(String(32), nullable = False, default = "running")
    completed_calls: Mapped[dict] = mapped_column(JSONB, nullable = False, default = dict)
    pending_tool: Mapped[dict | None] = mapped_column(JSONB, nullable = True)
    # Owner (users.id as a string, i.e. the JWT `sub`). Checked on /approve so
    # a run can only be resumed by the user who started it.
    user_id: Mapped[str | None] = mapped_column(String(64), nullable = True, index = True)
    # Model / reasoning effort the run was started with (see providers.registry).
    model: Mapped[str | None] = mapped_column(String(64), nullable = True)
    effort: Mapped[str | None] = mapped_column(String(16), nullable = True)
    # Connectors enabled for the conversation (see harness.connectors).
    connectors: Mapped[list] = mapped_column(JSONB, nullable = False, default = list, server_default = "[]")
    # Prompt-injection state for the run (harness.security): taint + events.
    security: Mapped[dict] = mapped_column(JSONB, nullable = False, default = dict, server_default = "{}")
    # The conversation this run belongs to (conversations.id). NULL for a
    # stateless /ask with no conversation_id, and for rows predating the table.
    # No FK: threads rows outlive conversations and are pruned separately.
    conversation_id: Mapped[str | None] = mapped_column(String(64), nullable = True, index = True)
    # How far into `message` has already been appended to the conversation
    # transcript. Everything from this index on is unpersisted, so a run that
    # paused for approval and resumed via /approve appends exactly the
    # remainder -- and appending twice is a no-op rather than a duplicate turn.
    persisted_upto: Mapped[int] = mapped_column(Integer, nullable = False, default = 0, server_default = "0")

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone = True), server_default = func.now(), nullable = False)

    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone = True), server_default = func.now(), onupdate = func.now(), nullable = False)

class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    emailVerified: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    image: Mapped[str | None] = mapped_column(String, nullable=True)
    role: Mapped[str] = mapped_column(String(32), nullable=False, server_default="user")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

class Account(Base):
    __tablename__ = "accounts"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    userId: Mapped[int] = mapped_column(Integer, nullable=False)
    type: Mapped[str] = mapped_column(String(255), nullable=False)
    provider: Mapped[str] = mapped_column(String(255), nullable=False)
    providerAccountId: Mapped[str] = mapped_column(String(255), nullable=False)
    refresh_token: Mapped[str | None] = mapped_column(String, nullable=True)
    access_token: Mapped[str | None] = mapped_column(String, nullable=True)
    expires_at: Mapped[int | None] = mapped_column(nullable=True)
    id_token: Mapped[str | None] = mapped_column(String, nullable=True)
    scope: Mapped[str | None] = mapped_column(String, nullable=True)
    session_state: Mapped[str | None] = mapped_column(String, nullable=True)
    token_type: Mapped[str | None] = mapped_column(String, nullable=True)

class Session(Base):
    __tablename__ = "sessions"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    userId: Mapped[int] = mapped_column(Integer, nullable=False)
    expires: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    sessionToken: Mapped[str] = mapped_column(String(255), nullable=False)

class VerificationToken(Base):
    __tablename__ = "verification_token"
    identifier: Mapped[str] = mapped_column(String, primary_key=True)
    token: Mapped[str] = mapped_column(String, primary_key=True)
    expires: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)



class Transaction(Base):
    __tablename__ = "transactions"
    id: Mapped[int] = mapped_column(primary_key = True, autoincrement = True)
    user_id: Mapped[int] = mapped_column(Integer, nullable = False, index = True)
    amount: Mapped[Decimal] = mapped_column(Numeric(12,4), nullable = False)
    kind: Mapped[str] = mapped_column(String(32), nullable = False)
    thread_id: Mapped[str | None] = mapped_column(String(32), nullable = True)
    balance_after: Mapped[Decimal] = mapped_column(Numeric(12,4), nullable = False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default = func.now(), nullable = False)

class UserMemory(Base):
    __tablename__ = "user_memory"
    id: Mapped[int] = mapped_column(primary_key = True, autoincrement = True)
    user_id: Mapped[int] = mapped_column(Integer, nullable = False, index = True)
    kind: Mapped[str] = mapped_column(String(32), nullable = False)          # preference | fact | correction
    content: Mapped[str] = mapped_column(String(1024), nullable = False)     # the remembered statement
    active: Mapped[bool] = mapped_column(nullable = False, default = True)   # supersede-don't-delete
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone = True), server_default = func.now(), nullable = False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone = True), server_default = func.now(), onupdate = func.now(), nullable = False)


class Episode(Base):
    __tablename__ = "episodes"
    id: Mapped[int] = mapped_column(primary_key = True, autoincrement = True)
    user_id: Mapped[int] = mapped_column(Integer, nullable = False, index = True)
    thread_id: Mapped[str] = mapped_column(String(64), nullable = False)     # conversation id (unique per user)
    title: Mapped[str] = mapped_column(String(200), nullable = False, default = "")  # first question, for the Chats rail
    summary: Mapped[str] = mapped_column(String(2048), nullable = False)
    embedding: Mapped[list[float]] = mapped_column(Vector(1536), nullable = False)
    embed_model: Mapped[str] = mapped_column(String(64), nullable = False)   # versioning guard
    active: Mapped[bool] = mapped_column(nullable = False, default = True)   # hide-don't-delete
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone = True), server_default = func.now(), nullable = False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone = True), server_default = func.now(), onupdate = func.now(), nullable = False)
    __table_args__ = (UniqueConstraint("user_id", "thread_id", name = "uq_episodes_user_thread"),)
    



class Conversation(Base):
    """One user-facing conversation: durable identity, context and rail entry.

    The ``threads`` row stays the per-RUN checkpoint; this is the thing many
    runs share. Before this table existed a conversation lived only in the
    browser tab's sessionStorage and was re-uploaded as ``AskRequest.history``
    every turn, so tool results never survived a turn and a chat could not be
    reopened. ``active_run_id`` is the cross-replica claim that keeps a
    conversation to one run at a time (see api/conversation_lock.py).

    ``user_id`` is the JWT ``sub`` as a string, like ``threads.user_id`` and
    ``document_chunks.user_id`` -- deliberately unlike ``episodes.user_id``,
    which is ``users.id``.
    """

    __tablename__ = "conversations"

    id: Mapped[str] = mapped_column(String(64), primary_key = True)           # uuid4().hex
    user_id: Mapped[str] = mapped_column(String(64), nullable = False, index = True)
    title: Mapped[str] = mapped_column(String(200), nullable = False, default = "")
    # What the conversation was started with. A later turn that leaves these
    # unset reuses them, so resuming on another device behaves the same.
    model: Mapped[str | None] = mapped_column(String(64), nullable = True)
    effort: Mapped[str | None] = mapped_column(String(16), nullable = True)
    connectors: Mapped[list] = mapped_column(JSONB, nullable = False, default = list, server_default = "[]")
    mode: Mapped[str] = mapped_column(String(16), nullable = False, default = "default", server_default = "default")
    docs_only: Mapped[bool] = mapped_column(Boolean, nullable = False, default = False, server_default = "false")
    # Rolling compaction of everything at or below summary_through_seq, so the
    # summarising call happens only when the window actually advances.
    summary_text: Mapped[str] = mapped_column(Text, nullable = False, default = "", server_default = "")
    summary_through_seq: Mapped[int] = mapped_column(Integer, nullable = False, default = 0, server_default = "0")
    # Next seq to hand out in conversation_messages; allocated under a row lock.
    next_seq: Mapped[int] = mapped_column(Integer, nullable = False, default = 0, server_default = "0")
    # Prompt-injection taint for the WHOLE conversation, not one run: a chat
    # that ingested a poisoned document is still tainted on the next turn.
    security: Mapped[dict] = mapped_column(JSONB, nullable = False, default = dict, server_default = "{}")
    active_run_id: Mapped[str | None] = mapped_column(String(64), nullable = True)
    active_run_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone = True), nullable = True)
    active: Mapped[bool] = mapped_column(Boolean, nullable = False, default = True, server_default = "true")

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone = True), server_default = func.now(), nullable = False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone = True), server_default = func.now(), onupdate = func.now(), nullable = False)


class ConversationMessage(Base):
    """One message of the durable transcript, in OpenAI wire shape.

    Append-only, and it keeps every role: ``extra`` carries ``tool_calls`` /
    ``tool_call_id``, so a later turn can still see what an earlier turn
    retrieved. One row per message rather than a JSONB blob on the
    conversation, because the blob would be rewritten in full on every step.
    """

    __tablename__ = "conversation_messages"

    id: Mapped[int] = mapped_column(primary_key = True, autoincrement = True)
    conversation_id: Mapped[str] = mapped_column(String(64), nullable = False)
    seq: Mapped[int] = mapped_column(Integer, nullable = False)               # order within the conversation
    role: Mapped[str] = mapped_column(String(16), nullable = False)           # user | assistant | tool
    content: Mapped[str] = mapped_column(Text, nullable = False, default = "")
    # tool_calls (assistant) / tool_call_id (tool) / ui -- everything the wire
    # format needs that is not role+content.
    extra: Mapped[dict] = mapped_column(JSONB, nullable = False, default = dict, server_default = "{}")
    run_id: Mapped[str | None] = mapped_column(String(64), nullable = True)   # which run produced it
    tokens: Mapped[int] = mapped_column(Integer, nullable = False, default = 0, server_default = "0")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone = True), server_default = func.now(), nullable = False)

    __table_args__ = (
        UniqueConstraint("conversation_id", "seq", name = "uq_convmsg_conv_seq"),
        Index("ix_convmsg_conv_seq", "conversation_id", "seq"),
    )


class DocumentChunk(Base):
    """One embedded passage of a document, in Postgres rather than a JSON file.

    ``user_id`` NULL is the shared corpus built by ``harness.retrieval.ingest``;
    a non-NULL ``user_id`` is that person's upload, and every query filters on
    it, so isolation is a WHERE clause rather than a process-local index.
    ``index_version`` lets a re-ingest write a new generation and drop the old
    one in the same transaction, so readers never see a half-built corpus.
    """

    __tablename__ = "document_chunks"
    id: Mapped[int] = mapped_column(primary_key = True, autoincrement = True)
    # the JWT ``sub`` as a string (NULL = the shared corpus), not users.id:
    # uploads are keyed by whatever subject the token carries.
    user_id: Mapped[str | None] = mapped_column(String(64), nullable = True, index = True)
    source: Mapped[str] = mapped_column(String(512), nullable = False)   # file name, shown as [source]
    chunk_index: Mapped[int] = mapped_column(Integer, nullable = False, default = 0)
    text: Mapped[str] = mapped_column(Text, nullable = False)
    embedding: Mapped[list[float]] = mapped_column(Vector(EMBED_DIM), nullable = False)
    embed_model: Mapped[str] = mapped_column(String(64), nullable = False)  # versioning guard
    index_version: Mapped[str] = mapped_column(String(32), nullable = False, server_default = "")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone = True), server_default = func.now(), nullable = False)

    __table_args__ = (
        Index("ix_document_chunks_user_source", "user_id", "source"),
        # HNSW under the cosine operator class -- the same distance the query
        # (<=>) asks for, which is what makes the index usable at all.
        Index(
            "ix_document_chunks_embedding",
            "embedding",
            postgresql_using = "hnsw",
            postgresql_with = {"m": 16, "ef_construction": 64},
            postgresql_ops = {"embedding": "vector_cosine_ops"},
        ),
    )


class VaultCredential(Base):
    """A third-party secret, encrypted with the vault master key. ``user_id``
    NULL means an operator-provided (system) credential. The plaintext is
    only ever decrypted inside the vault proxy."""
    __tablename__ = "vault_credentials"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    provider: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    label: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    kind: Mapped[str] = mapped_column(String(16), nullable=False, default="api_key")
    ciphertext: Mapped[str] = mapped_column(String, nullable=False)
    fingerprint: Mapped[str] = mapped_column(String(16), nullable=False)
    scopes: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class VaultConsent(Base):
    """Standing permission for the agent to use a provider on the user's
    behalf. ``allow_write`` only makes write calls *eligible*; each one still
    pauses for human approval."""
    __tablename__ = "vault_consents"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    provider: Mapped[str] = mapped_column(String(64), nullable=False)
    credential_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    allow_write: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    granted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class UserSettings(Base):
    """Personalisation the user sets once: how to address them, tone, timezone,
    and free-text custom instructions that ride along in every system prompt."""
    __tablename__ = "user_settings"
    user_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    display_name: Mapped[str] = mapped_column(String(80), nullable=False, default="")
    instructions: Mapped[str] = mapped_column(String(2000), nullable=False, default="")
    tone: Mapped[str] = mapped_column(String(16), nullable=False, default="balanced")   # concise | balanced | detailed
    timezone: Mapped[str] = mapped_column(String(64), nullable=False, default="UTC")
    language: Mapped[str] = mapped_column(String(16), nullable=False, default="")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)


class ScheduledTask(Base):
    """A question the agent asks on the user's behalf on a schedule (a daily
    briefing, a weekly digest...). Results land in the Chats rail as episodes."""
    __tablename__ = "scheduled_tasks"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(120), nullable=False)
    question: Mapped[str] = mapped_column(String(4000), nullable=False)
    every_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)      # interval schedule
    daily_at: Mapped[str | None] = mapped_column(String(5), nullable=True)         # "HH:MM" in the user's timezone
    connectors: Mapped[list] = mapped_column(JSONB, nullable=False, default=list, server_default="[]")
    mode: Mapped[str] = mapped_column(String(16), nullable=False, default="default")
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    next_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_status: Mapped[str] = mapped_column(String(32), nullable=False, default="never")
    last_run_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    last_answer: Mapped[str] = mapped_column(String(4000), nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
