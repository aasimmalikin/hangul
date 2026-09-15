"""add user_id to threads

Threads (agent checkpoints) had no owner. /approve resumes a thread by id,
so any signed-in caller who knew a run id could approve someone else's
pending action. The owner is now recorded on every checkpoint and checked
before a resume.

Revision ID: 7a1c2e9d4b10
Revises: 591efb74e035
Create Date: 2026-09-15 18:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '7a1c2e9d4b10'
down_revision: Union[str, Sequence[str], None] = '591efb74e035'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("threads", sa.Column("user_id", sa.String(64), nullable=True))
    op.create_index("ix_threads_user_id", "threads", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_threads_user_id", table_name="threads")
    op.drop_column("threads", "user_id")
