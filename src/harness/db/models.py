from datetime import datetime
from sqlalchemy import UniqueConstraint, DateTime, Integer, String, func
from sqlalchemy import Numeric
from decimal import Decimal
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from harness.db.base import Base
from pgvector.sqlalchemy import Vector

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
    

