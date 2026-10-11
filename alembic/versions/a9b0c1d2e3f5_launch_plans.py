"""launch_plans: plans for starting a business (harness.launch)

Revision ID: a9b0c1d2e3f5
Revises: f8a9b0c1d2e4
Create Date: 2026-10-07 18:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


# revision identifiers, used by Alembic.
revision: str = 'a9b0c1d2e3f5'
down_revision: Union[str, Sequence[str], None] = 'f8a9b0c1d2e4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "launch_plans",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.Integer, nullable=False, index=True),
        sa.Column("conversation_id", sa.String(32), nullable=True),
        sa.Column("title", sa.String(120), nullable=False),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("city", sa.String(80), nullable=False, server_default=""),
        sa.Column("area", sa.String(120), nullable=False, server_default=""),
        sa.Column("answers", JSONB, nullable=False, server_default="{}"),
        sa.Column("items", JSONB, nullable=False, server_default="[]"),
        sa.Column("assumptions", JSONB, nullable=False, server_default="{}"),
        sa.Column("benchmarks", JSONB, nullable=False, server_default="[]"),
        sa.Column("suppliers", JSONB, nullable=False, server_default="[]"),
        sa.Column("status", sa.String(16), nullable=False, server_default="ready"),
        sa.Column("sourced", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("sourced_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("progress", JSONB, nullable=False, server_default="{}"),
        sa.Column("refreshes", sa.Integer, nullable=False, server_default="0"),
        sa.Column("error", sa.String(300), nullable=False, server_default=""),
        sa.Column("cost_usd", sa.Numeric(12, 6), nullable=False, server_default="0"),
        sa.Column("active", sa.Boolean, nullable=False, server_default="true"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("launch_plans")
