"""conversations + conversation_messages: a server-owned conversation

Until now a conversation existed only in the browser tab's sessionStorage and
was re-uploaded as `AskRequest.history` on every request, so `threads` (keyed
by run_id) was a per-RUN checkpoint and nothing linked the runs of one chat.
This adds the conversation itself and its append-only transcript, plus
`threads.conversation_id` so a run points back at the chat it belongs to.

Nothing reads these tables at this revision -- applying it is a no-op for
behaviour.

Revision ID: c5d6e7f8a9b0
Revises: b2c3d4e5f6a7
Create Date: 2026-09-24 12:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'c5d6e7f8a9b0'
down_revision: Union[str, Sequence[str], None] = 'b2c3d4e5f6a7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "conversations",
        sa.Column("id", sa.String(64), primary_key=True),
        # the JWT `sub` as a string, like threads.user_id (NOT users.id)
        sa.Column("user_id", sa.String(64), nullable=False),
        sa.Column("title", sa.String(200), nullable=False, server_default=""),
        sa.Column("model", sa.String(64), nullable=True),
        sa.Column("effort", sa.String(16), nullable=True),
        sa.Column("connectors", postgresql.JSONB, nullable=False, server_default="[]"),
        sa.Column("mode", sa.String(16), nullable=False, server_default="default"),
        sa.Column("docs_only", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("summary_text", sa.Text, nullable=False, server_default=""),
        sa.Column("summary_through_seq", sa.Integer, nullable=False, server_default="0"),
        sa.Column("next_seq", sa.Integer, nullable=False, server_default="0"),
        sa.Column("security", postgresql.JSONB, nullable=False, server_default="{}"),
        # the cross-replica claim: one run at a time per conversation
        sa.Column("active_run_id", sa.String(64), nullable=True),
        sa.Column("active_run_started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("active", sa.Boolean, nullable=False, server_default="true"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_conversations_user_id", "conversations", ["user_id"])
    # the Chats rail query: this user's active conversations, newest first
    op.create_index("ix_conversations_user_active_updated", "conversations",
                    ["user_id", "active", "updated_at"])

    op.create_table(
        "conversation_messages",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("conversation_id", sa.String(64), nullable=False),
        sa.Column("seq", sa.Integer, nullable=False),
        sa.Column("role", sa.String(16), nullable=False),
        sa.Column("content", sa.Text, nullable=False, server_default=""),
        sa.Column("extra", postgresql.JSONB, nullable=False, server_default="{}"),
        sa.Column("run_id", sa.String(64), nullable=True),
        sa.Column("tokens", sa.Integer, nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    # seq is allocated from conversations.next_seq under a row lock; the unique
    # constraint is what turns a bug there into an error instead of a silent
    # reordering of someone's transcript.
    op.create_unique_constraint("uq_convmsg_conv_seq", "conversation_messages",
                                ["conversation_id", "seq"])
    op.create_index("ix_convmsg_conv_seq", "conversation_messages",
                    ["conversation_id", "seq"])

    op.add_column("threads", sa.Column("conversation_id", sa.String(64), nullable=True))
    op.create_index("ix_threads_conversation_id", "threads", ["conversation_id"])
    # how much of threads.message is already in the transcript (see the model)
    op.add_column("threads", sa.Column("persisted_upto", sa.Integer, nullable=False,
                                       server_default="0"))


def downgrade() -> None:
    op.drop_column("threads", "persisted_upto")
    op.drop_index("ix_threads_conversation_id", table_name="threads")
    op.drop_column("threads", "conversation_id")
    op.drop_index("ix_convmsg_conv_seq", table_name="conversation_messages")
    op.drop_constraint("uq_convmsg_conv_seq", "conversation_messages", type_="unique")
    op.drop_table("conversation_messages")
    op.drop_index("ix_conversations_user_active_updated", table_name="conversations")
    op.drop_index("ix_conversations_user_id", table_name="conversations")
    op.drop_table("conversations")
