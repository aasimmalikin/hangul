"""kept: where reminders/list items/notes/memories came from, and kept_actions

The Kept tab (formerly My stuff) shows each instruction in the user's own
words and opens the chat it came from, so the rows a run creates record the
conversation id and the question. kept_actions records outward actions that
have no row of their own (an email sent, an event added, a file made).

Revision ID: e2f3a4b5c6d7
Revises: f1a2b3c4d5e6
Create Date: 2026-10-05 16:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e2f3a4b5c6d7'
down_revision: Union[str, Sequence[str], None] = 'f1a2b3c4d5e6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABLES = ("reminders", "todo_items", "notes", "user_memory")


def upgrade() -> None:
    for t in TABLES:
        op.add_column(t, sa.Column("conversation_id", sa.String(32), nullable=True))
        op.add_column(t, sa.Column("said", sa.String(500), nullable=True))
    op.create_table(
        "kept_actions",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.String(64), nullable=False),
        sa.Column("conversation_id", sa.String(32), nullable=True),
        sa.Column("said", sa.String(500), nullable=True),
        sa.Column("tool", sa.String(100), nullable=False),
        sa.Column("app", sa.String(32), nullable=False),
        sa.Column("did", sa.String(300), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_kept_actions_user_created", "kept_actions", ["user_id", "created_at"])


def downgrade() -> None:
    op.drop_table("kept_actions")
    for t in TABLES:
        op.drop_column(t, "said")
        op.drop_column(t, "conversation_id")
