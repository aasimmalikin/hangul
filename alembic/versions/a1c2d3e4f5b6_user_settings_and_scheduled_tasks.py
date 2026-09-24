"""user settings and scheduled tasks

Personalisation (custom instructions, tone, timezone) and scheduled tasks
(questions the agent runs on a schedule) for the personal-assistant features.

Revision ID: a1c2d3e4f5b6
Revises: f7b2c3d4e5a6
Create Date: 2026-09-18 20:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'a1c2d3e4f5b6'
down_revision: Union[str, Sequence[str], None] = 'f7b2c3d4e5a6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "user_settings",
        sa.Column("user_id", sa.Integer, primary_key=True),
        sa.Column("display_name", sa.String(80), nullable=False, server_default=""),
        sa.Column("instructions", sa.String(2000), nullable=False, server_default=""),
        sa.Column("tone", sa.String(16), nullable=False, server_default="balanced"),
        sa.Column("timezone", sa.String(64), nullable=False, server_default="UTC"),
        sa.Column("language", sa.String(16), nullable=False, server_default=""),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_table(
        "scheduled_tasks",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.Integer, nullable=False),
        sa.Column("title", sa.String(120), nullable=False),
        sa.Column("question", sa.String(4000), nullable=False),
        sa.Column("every_minutes", sa.Integer, nullable=True),
        sa.Column("daily_at", sa.String(5), nullable=True),
        sa.Column("connectors", postgresql.JSONB, nullable=False, server_default="[]"),
        sa.Column("mode", sa.String(16), nullable=False, server_default="default"),
        sa.Column("enabled", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("next_run_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_run_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_status", sa.String(32), nullable=False, server_default="never"),
        sa.Column("last_run_id", sa.String(64), nullable=True),
        sa.Column("last_answer", sa.String(4000), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_scheduled_tasks_user_id", "scheduled_tasks", ["user_id"])
    op.create_index("ix_scheduled_tasks_next_run_at", "scheduled_tasks", ["next_run_at"])


def downgrade() -> None:
    op.drop_index("ix_scheduled_tasks_next_run_at", table_name="scheduled_tasks")
    op.drop_index("ix_scheduled_tasks_user_id", table_name="scheduled_tasks")
    op.drop_table("scheduled_tasks")
    op.drop_table("user_settings")
