"""churn_feedback: why people open "Cancel plan" and what they did

Revision ID: e4f5a6b7c8d9
Revises: d3e4f5a6b7c8
Create Date: 2026-10-03 14:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e4f5a6b7c8d9'
down_revision: Union[str, Sequence[str], None] = 'd3e4f5a6b7c8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "churn_feedback",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.Integer, nullable=False),
        sa.Column("plan", sa.String(16), nullable=False),
        sa.Column("reason", sa.String(32), nullable=False),
        sa.Column("detail", sa.String(1000), nullable=False, server_default=""),
        sa.Column("outcome", sa.String(16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_churn_feedback_user_id", "churn_feedback", ["user_id"])
    op.create_index("ix_churn_feedback_created_at", "churn_feedback", ["created_at"])


def downgrade() -> None:
    op.drop_table("churn_feedback")
