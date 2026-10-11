"""promises, promise_scans: Kept your word (harness.promises)

Revision ID: d4e5f6a7b8c0
Revises: c2d3e4f5a6b8
Create Date: 2026-10-08 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


# revision identifiers, used by Alembic.
revision: str = 'd4e5f6a7b8c0'
down_revision: Union[str, Sequence[str], None] = 'c2d3e4f5a6b8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "promises",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.Integer, nullable=False),
        sa.Column("direction", sa.String(8), nullable=False),
        sa.Column("what", sa.String(300), nullable=False),
        sa.Column("who", sa.String(120), nullable=False, server_default=""),
        sa.Column("who_email", sa.String(255), nullable=False, server_default=""),
        sa.Column("due_on", sa.Date, nullable=True),
        sa.Column("source", sa.String(16), nullable=False),
        sa.Column("source_ref", sa.String(128), nullable=False, server_default=""),
        sa.Column("thread_ref", sa.String(128), nullable=False, server_default=""),
        sa.Column("quote", sa.String(500), nullable=False, server_default=""),
        sa.Column("status", sa.String(16), nullable=False, server_default="open"),
        sa.Column("last_contact_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("nudged_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("chased_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("done_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("conversation_id", sa.String(32), nullable=True),
        sa.Column("said", sa.String(500), nullable=True),
    )
    op.create_index("ix_promises_user_status", "promises", ["user_id", "status"])
    op.create_table(
        "promise_scans",
        sa.Column("user_id", sa.Integer, primary_key=True),
        sa.Column("email_on", sa.Boolean, nullable=False, server_default="true"),
        sa.Column("email_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("meetings_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("seen", JSONB, nullable=False, server_default="[]"),
        sa.Column("asked", JSONB, nullable=False, server_default="[]"),
    )


def downgrade() -> None:
    op.drop_table("promise_scans")
    op.drop_index("ix_promises_user_status", table_name="promises")
    op.drop_table("promises")
