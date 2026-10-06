"""scheduled_tasks: drop auto_approve (scheduled runs now use one fixed rule, harness.preapproval)

Revision ID: d6e7f8a9b0c1
Revises: b4c5d6e7f8a9
Create Date: 2026-10-06 20:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'd6e7f8a9b0c1'
down_revision: Union[str, Sequence[str], None] = 'b4c5d6e7f8a9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_column("scheduled_tasks", "auto_approve")


def downgrade() -> None:
    op.add_column("scheduled_tasks", sa.Column("auto_approve", postgresql.JSONB, nullable=False,
                                               server_default="[]"))
