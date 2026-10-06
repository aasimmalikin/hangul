"""scheduled_tasks: weekday schedules, one-off runs and pre-approved actions

Revision ID: b4c5d6e7f8a9
Revises: a3b4c5d6e7f8
Create Date: 2026-10-06 18:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'b4c5d6e7f8a9'
down_revision: Union[str, Sequence[str], None] = 'a3b4c5d6e7f8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("scheduled_tasks", sa.Column("days", sa.Integer, nullable=True))
    op.add_column("scheduled_tasks", sa.Column("run_on", sa.Date, nullable=True))
    op.add_column("scheduled_tasks", sa.Column("auto_approve", postgresql.JSONB, nullable=False,
                                               server_default="[]"))


def downgrade() -> None:
    op.drop_column("scheduled_tasks", "auto_approve")
    op.drop_column("scheduled_tasks", "run_on")
    op.drop_column("scheduled_tasks", "days")
