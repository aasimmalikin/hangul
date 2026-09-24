"""add security state to threads

Prompt-injection state for a run (harness.security): whether the context is
tainted by suspicious tool content and the events raised, so /approve resumes
with the same step-up rules.

Revision ID: f7b2c3d4e5a6
Revises: e6a1b2c3d4f5
Create Date: 2026-09-18 18:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'f7b2c3d4e5a6'
down_revision: Union[str, Sequence[str], None] = 'e6a1b2c3d4f5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("threads", sa.Column("security", postgresql.JSONB, nullable=False, server_default="{}"))


def downgrade() -> None:
    op.drop_column("threads", "security")
