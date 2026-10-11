from datetime import date, datetime
from sqlalchemy import Boolean, Date, Index, UniqueConstraint, DateTime, Integer, String, Text, func
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
    # Billing (harness.billing). Written only by the Dodo Payments webhook.
    plan: Mapped[str] = mapped_column(String(16), nullable=False, server_default="free")
    plan_status: Mapped[str | None] = mapped_column(String(16), nullable=True)
    # Start of the current paid period: the allowance counts spend since then.
    plan_period_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    plan_renews_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    plan_ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    billing_customer_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    billing_subscription_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    # which price the plan was bought at: "in" (rupees, smaller allowance) or "intl";
    # and "month" or "year" (a yearly plan still gets its allowance month by month)
    plan_region: Mapped[str] = mapped_column(String(8), nullable=False, default="intl", server_default="intl")
    plan_interval: Mapped[str] = mapped_column(String(8), nullable=False, default="month", server_default="month")
    # brand slots bought on top of the plan's (one-time purchases, harness.brands)
    extra_brands: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")

class BillingEvent(Base):
    """One row per payment-provider webhook delivery (id = its `webhook-id`),
    so a retried delivery is applied once."""
    __tablename__ = "billing_events"
    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    event_name: Mapped[str] = mapped_column(String(64), nullable=False)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

class WhatsAppLink(Base):
    """A user's WhatsApp number (harness/whatsapp). Linking: the app shows a code,
    the user sends it from WhatsApp, and that number is tied to the account.
    ``last_inbound_at`` decides whether free-form replies are still allowed
    (Meta's 24-hour window); ``pending_text`` holds a brief that had to wait for it."""
    __tablename__ = "whatsapp_links"
    user_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    phone: Mapped[str | None] = mapped_column(String(20), nullable=True, unique=True)          # E.164 digits, no "+"
    link_code_hash: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    link_code_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    linked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    conversation_id: Mapped[str | None] = mapped_column(String(32), nullable=True)            # the WhatsApp chat in Chats
    last_inbound_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    pending_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

class PushSubscription(Base):
    """One browser or installed app that agreed to notifications (harness/push.py).
    ``endpoint`` is the push service's address for that device; ``p256dh``/``auth``
    encrypt the message so the push service can't read it. A device belongs to
    whoever subscribed it last (a shared browser that signs in as someone else)."""
    __tablename__ = "push_subscriptions"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    endpoint: Mapped[str] = mapped_column(String(1024), nullable=False, unique=True)
    p256dh: Mapped[str] = mapped_column(String(255), nullable=False)
    auth: Mapped[str] = mapped_column(String(64), nullable=False)
    user_agent: Mapped[str | None] = mapped_column(String(200), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    last_sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

class WhatsAppInbound(Base):
    """Message ids already handled: Meta retries deliveries, a message is answered once."""
    __tablename__ = "whatsapp_inbound"
    wamid: Mapped[str] = mapped_column(String(128), primary_key=True)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

class ChurnFeedback(Base):
    """Why someone opened "Cancel plan", and what they did: kept the plan,
    switched to a cheaper one, or cancelled. The admin page summarises it."""
    __tablename__ = "churn_feedback"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    plan: Mapped[str] = mapped_column(String(16), nullable=False)
    reason: Mapped[str] = mapped_column(String(32), nullable=False)
    detail: Mapped[str] = mapped_column(String(1000), nullable=False, default="", server_default="")
    outcome: Mapped[str] = mapped_column(String(16), nullable=False)      # kept | downgraded | cancelled
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False, index=True)

class MoodCheckin(Base):
    """The morning check-in on Today: how the user said they feel, once per
    local day. The run of consecutive days is the "mornings together" streak,
    and today's mood shapes how Hangul plans and words things (db/checkins.py)."""
    __tablename__ = "mood_checkins"
    __table_args__ = (UniqueConstraint("user_id", "day", name="uq_mood_checkins_user_day"),)
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)       # the JWT sub, like conversations.user_id
    day: Mapped[str] = mapped_column(String(10), nullable=False)                         # local date, YYYY-MM-DD
    mood: Mapped[str] = mapped_column(String(16), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

class WaitlistEntry(Base):
    """Pre-registration before launch (/join, db/waitlist.py): an email, not an
    account. Who they are and which plan interests them are optional; source is
    the ?ref= / utm_source the visitor arrived with (e.g. "x")."""
    __tablename__ = "waitlist"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    email: Mapped[str] = mapped_column(String(254), nullable=False, unique=True)          # lower-cased
    persona: Mapped[str] = mapped_column(String(16), nullable=False, server_default="")    # db/settings.PERSONAS key or ""
    interest: Mapped[str] = mapped_column(String(8), nullable=False, server_default="")    # free / plus / pro or ""
    source: Mapped[str] = mapped_column(String(40), nullable=False, server_default="")
    trade: Mapped[str] = mapped_column(String(16), nullable=False, server_default="")      # kind of business (web BUSINESS_KINDS) or ""
    city: Mapped[str] = mapped_column(String(80), nullable=False, server_default="")
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
    # where it came from (harness/provenance.py): the chat and the user's words, for the Kept tab
    conversation_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    said: Mapped[str | None] = mapped_column(String(500), nullable=True)


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
    # the brand (brands.id) the chat makes things for; NULL = none
    brand_id: Mapped[int | None] = mapped_column(Integer, nullable = True)
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
    # True: follow the timezone of whatever device the user is on (sent by the
    # web app); False: the user pinned `timezone` by hand in Personalisation.
    timezone_auto: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")
    # home city: the Today screen's weather, and the default for "near me"
    city: Mapped[str] = mapped_column(String(80), nullable=False, default="", server_default="")
    # where the user usually sets off from: the Today screen's "Leave by" (sent to OpenStreetMap to route)
    home_address: Mapped[str] = mapped_column(String(200), nullable=False, default="", server_default="")
    # who they are (db/settings.PERSONAS): shapes answers, starter prompts and the plan we suggest
    persona: Mapped[str] = mapped_column(String(16), nullable=False, default="", server_default="")
    # finished (or skipped) the first-run walkthrough
    onboarded: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
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
    # also email each result to the user (a "daily brief"), via harness.notify
    deliver_email: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    # with daily_at: run only on these weekdays (bit 0 = Monday … bit 6 = Sunday), e.g. 31 = weekdays
    days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # with daily_at: run once, on this local date, then switch off
    run_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    next_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_status: Mapped[str] = mapped_column(String(32), nullable=False, default="never")
    last_run_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    last_answer: Mapped[str] = mapped_column(String(4000), nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class Reminder(Base):
    """"Remind me to … at …": fired once by the scheduler, shown in the app's
    bell and emailed. ``status``: pending -> sent -> done | cancelled."""
    __tablename__ = "reminders"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    text: Mapped[str] = mapped_column(String(500), nullable=False)
    due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending", server_default="pending")
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    emailed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    # where it came from (harness/provenance.py): the chat and the user's words, for the Kept tab
    conversation_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    said: Mapped[str | None] = mapped_column(String(500), nullable=True)


class TodoItem(Base):
    """One line on one of the user's lists ("To-do", "Shopping", …)."""
    __tablename__ = "todo_items"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    list_name: Mapped[str] = mapped_column(String(60), nullable=False, default="To-do", server_default="To-do")
    text: Mapped[str] = mapped_column(String(500), nullable=False)
    done: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    done_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # where it came from (harness/provenance.py): the chat and the user's words, for the Kept tab
    conversation_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    said: Mapped[str | None] = mapped_column(String(500), nullable=True)


class Note(Base):
    """A quick note the user asked to keep ("note: car service due in March")."""
    __tablename__ = "notes"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    text: Mapped[str] = mapped_column(String(4000), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    # where it came from (harness/provenance.py): the chat and the user's words, for the Kept tab
    conversation_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    said: Mapped[str | None] = mapped_column(String(500), nullable=True)


class KeptAction(Base):
    """Something Hangul did outside the chat because the user asked: an email
    sent, an event added, a file made. Reminders, lists, notes and memories
    have their own rows; this is the record for everything else (Kept tab)."""
    __tablename__ = "kept_actions"
    __table_args__ = (Index("ix_kept_actions_user_created", "user_id", "created_at"),)
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(String(64), nullable=False)          # JWT sub
    conversation_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    said: Mapped[str | None] = mapped_column(String(500), nullable=True)
    tool: Mapped[str] = mapped_column(String(100), nullable=False)
    app: Mapped[str] = mapped_column(String(32), nullable=False)
    did: Mapped[str] = mapped_column(String(300), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class Brand(Base):
    """A business look the user set up once (harness.brands): colours, style,
    voice, font and logo, applied to what Hangul makes while the brand is on.
    Hidden, not deleted (``active``); a hidden brand frees its slot."""
    __tablename__ = "brands"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    kind: Mapped[str] = mapped_column(String(32), nullable=False, default="", server_default="")
    look: Mapped[str] = mapped_column(String(48), nullable=False, default="", server_default="")
    colors: Mapped[list] = mapped_column(JSONB, nullable=False, default=list, server_default="[]")   # [{role, hex}]
    style: Mapped[str] = mapped_column(String(300), nullable=False, default="", server_default="")
    voice: Mapped[str] = mapped_column(String(300), nullable=False, default="", server_default="")
    font: Mapped[str] = mapped_column(String(32), nullable=False, default="sans", server_default="sans")
    logo: Mapped[str] = mapped_column(String(200), nullable=False, default="", server_default="")    # basename in the user folder
    # the kit an agency fills in once per client (brands v2)
    logo_dark: Mapped[str] = mapped_column(String(200), nullable=False, default="", server_default="")   # for dark backgrounds
    handle: Mapped[str] = mapped_column(String(60), nullable=False, default="", server_default="")       # @chinarcafe
    website: Mapped[str] = mapped_column(String(200), nullable=False, default="", server_default="")
    cta: Mapped[str] = mapped_column(String(60), nullable=False, default="", server_default="")          # "Order on Zomato"
    footer: Mapped[str] = mapped_column(String(120), nullable=False, default="", server_default="")      # address / phone line
    hashtags: Mapped[list] = mapped_column(JSONB, nullable=False, default=list, server_default="[]")    # [{name, tags: [..]}]
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)


class BrandAsset(Base):
    """A photo in a brand's library (the file lives in the user folder), so a
    social media manager uploads product shots once and reuses them."""
    __tablename__ = "brand_assets"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    brand_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    user_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    width: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    height: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class BrandPost(Base):
    """One post made for a brand: the words and layout, every size rendered (a
    carousel has one file per slide and size), the captions written for it,
    and the client's review (review links, harness.brands.review)."""
    __tablename__ = "brand_posts"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    brand_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    user_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    kind: Mapped[str] = mapped_column(String(16), nullable=False, default="single", server_default="single")  # single | carousel
    layout: Mapped[str] = mapped_column(String(24), nullable=False, default="band", server_default="band")
    words: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict, server_default="{}")
    slides: Mapped[list] = mapped_column(JSONB, nullable=False, default=list, server_default="[]")
    sizes: Mapped[list] = mapped_column(JSONB, nullable=False, default=list, server_default="[]")
    files: Mapped[list] = mapped_column(JSONB, nullable=False, default=list, server_default="[]")
    captions: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict, server_default="{}")
    review_status: Mapped[str] = mapped_column(String(16), nullable=False, default="none", server_default="none")  # none | waiting | approved | changes
    review_comment: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class LaunchPlan(Base):
    """A plan for starting a business (harness.launch): the user's answers, the
    checklist with prices (estimates until sourced), the assumptions they edit,
    industry benchmarks and nearby suppliers. The numbers are computed from
    these on every read (launch/economics.py), never stored. Hidden, not
    deleted (``active``)."""
    __tablename__ = "launch_plans"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    conversation_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    title: Mapped[str] = mapped_column(String(120), nullable=False)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    city: Mapped[str] = mapped_column(String(80), nullable=False, default="", server_default="")
    area: Mapped[str] = mapped_column(String(120), nullable=False, default="", server_default="")
    answers: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict, server_default="{}")
    items: Mapped[list] = mapped_column(JSONB, nullable=False, default=list, server_default="[]")
    assumptions: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict, server_default="{}")
    benchmarks: Mapped[list] = mapped_column(JSONB, nullable=False, default=list, server_default="[]")
    suppliers: Mapped[list] = mapped_column(JSONB, nullable=False, default=list, server_default="[]")
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="ready", server_default="ready")  # ready | sourcing | failed
    sourced: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")    # counts against the plan's monthly sourced plans
    sourced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    progress: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict, server_default="{}")          # {stage, done, total}
    refreshes: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    error: Mapped[str] = mapped_column(String(300), nullable=False, default="", server_default="")
    cost_usd: Mapped[Decimal] = mapped_column(Numeric(12, 6), nullable=False, default=Decimal("0"), server_default="0")
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)


class Customer(Base):
    """A shop's customer (db/customers.py): the owner's own list of regulars, with a
    phone, a birthday (the year is optional) and how often they come in. Hidden,
    not deleted (``active``)."""
    __tablename__ = "customers"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    business_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    phone: Mapped[str] = mapped_column(String(20), nullable=False, default="", server_default="")    # +91… or ""
    birth_month: Mapped[int | None] = mapped_column(Integer, nullable=True)
    birth_day: Mapped[int | None] = mapped_column(Integer, nullable=True)
    birth_year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    note: Mapped[str] = mapped_column(String(200), nullable=False, default="", server_default="")
    visits: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    last_visit: Mapped[date | None] = mapped_column(Date, nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    conversation_id: Mapped[str | None] = mapped_column(String(32), nullable=True)    # provenance, like reminders
    said: Mapped[str | None] = mapped_column(String(500), nullable=True)


class Business(Base):
    """A business the user runs (harness.sales, "How's business"): what it is,
    where (for its weather), and optionally the launch plan it came from (its
    break-even and margins) and the brand its posts use. Hidden, not deleted."""
    __tablename__ = "businesses"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    kind: Mapped[str] = mapped_column(String(32), nullable=False, default="retail_shop", server_default="retail_shop")
    city: Mapped[str] = mapped_column(String(80), nullable=False, default="", server_default="")
    lat: Mapped[float | None] = mapped_column(Numeric(9, 5), nullable=True)
    lon: Mapped[float | None] = mapped_column(Numeric(9, 5), nullable=True)
    brand_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    launch_plan_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    nudges: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")   # evening slow-day alert
    nudged: Mapped[list] = mapped_column(JSONB, nullable=False, default=list, server_default="[]")       # ISO dates alerted (last few)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class BusinessDay(Base):
    """One day's takings for a business: what the owner logged or imported,
    and that day's weather (filled in later, for the forecast)."""
    __tablename__ = "business_days"
    __table_args__ = (UniqueConstraint("business_id", "day", name="uq_business_day"),)
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    business_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    day: Mapped[date] = mapped_column(Date, nullable=False)
    sales: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False, default=Decimal(0))
    bills: Mapped[int | None] = mapped_column(Integer, nullable=True)
    closed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    partial: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")   # not the whole day: kept out of the forecast
    promo: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")     # an offer ran that day
    source: Mapped[str] = mapped_column(String(16), nullable=False, default="chat", server_default="chat")  # chat | page | import | photo
    note: Mapped[str] = mapped_column(String(200), nullable=False, default="", server_default="")
    rain_mm: Mapped[float | None] = mapped_column(Numeric(6, 1), nullable=True)
    tmax: Mapped[float | None] = mapped_column(Numeric(5, 1), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)


class BusinessEvent(Base):
    """Things that happened to a business on a day: a suggestion the owner used
    (counts against Plus's weekly one), an offer they planned, a note."""
    __tablename__ = "business_events"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    business_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    day: Mapped[date] = mapped_column(Date, nullable=False)
    kind: Mapped[str] = mapped_column(String(24), nullable=False)          # suggestion_used | offer
    detail: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict, server_default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class Mission(Base):
    """A job Hangul carries through on its own over days (harness.missions):
    a fixed list of steps it ticks off, pausing only where the owner must
    decide. ``kind`` picks the template (``slow_day``, ``monthly_report``);
    one mission per (user, kind, business, day), so a tick that runs twice
    never starts the same job twice."""
    __tablename__ = "missions"
    __table_args__ = (UniqueConstraint("user_id", "kind", "business_id", "target_day", name="uq_mission"),)
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    kind: Mapped[str] = mapped_column(String(24), nullable=False)
    business_id: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")   # 0 = none
    target_day: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="active", server_default="active")  # active | waiting | done | cancelled | expired
    steps: Mapped[list] = mapped_column(JSONB, nullable=False, default=list, server_default="[]")
    data: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict, server_default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)


class MissionTrust(Base):
    """Earned autonomy: how many times in a row the owner approved one kind of
    action (``scope``, e.g. ``slow_day:12``), and whether they let Hangul go
    ahead without asking. Revocable at any time; a rejection resets the run."""
    __tablename__ = "mission_trust"
    __table_args__ = (UniqueConstraint("user_id", "scope", name="uq_mission_trust"),)
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    scope: Mapped[str] = mapped_column(String(48), nullable=False)
    streak: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    auto: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    offered: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)


class Promise(Base):
    """Something someone said they'd do (harness.promises): ``mine`` = the user
    promised it, ``theirs`` = someone promised the user. Found in email, told
    after a meeting, or added in chat. ``status``: open -> done | dropped.
    ``last_contact_at``: the other side wrote back (theirs) or the user wrote
    to them (mine) after the promise, so it may already be kept."""
    __tablename__ = "promises"
    __table_args__ = (Index("ix_promises_user_status", "user_id", "status"),)
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, nullable=False)
    direction: Mapped[str] = mapped_column(String(8), nullable=False)              # mine | theirs
    what: Mapped[str] = mapped_column(String(300), nullable=False)
    who: Mapped[str] = mapped_column(String(120), nullable=False, default="", server_default="")
    who_email: Mapped[str] = mapped_column(String(255), nullable=False, default="", server_default="")
    due_on: Mapped[date | None] = mapped_column(Date, nullable=True)                # the user's local date
    source: Mapped[str] = mapped_column(String(16), nullable=False)                 # email | meeting | chat
    source_ref: Mapped[str] = mapped_column(String(128), nullable=False, default="", server_default="")  # message / event id
    thread_ref: Mapped[str] = mapped_column(String(128), nullable=False, default="", server_default="")  # Gmail thread
    quote: Mapped[str] = mapped_column(String(500), nullable=False, default="", server_default="")
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="open", server_default="open")
    last_contact_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    nudged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    chased_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    done_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    # where it came from (harness/provenance.py): the chat and the user's words, for the Kept tab
    conversation_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    said: Mapped[str | None] = mapped_column(String(500), nullable=True)


class PromiseScan(Base):
    """Per user: when email was last read for promises, which messages and
    meetings were already handled, and whether email reading is switched on."""
    __tablename__ = "promise_scans"
    user_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email_on: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")
    email_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    meetings_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    seen: Mapped[list] = mapped_column(JSONB, nullable=False, default=list, server_default="[]")       # Gmail message ids
    asked: Mapped[list] = mapped_column(JSONB, nullable=False, default=list, server_default="[]")      # [{id, summary, with, emails, at}]
