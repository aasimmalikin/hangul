"""add connectors to threads

Which connectors (harness.connectors) the user had switched on for the
conversation, so /approve resumes with the same tool set.

Revision ID: e6a1b2c3d4f5
Revises: d5f8a2b3c4e6
Create Date: 2026-09-18 16:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'e6a1b2c3d4f5'
down_revision: Union[str, Sequence[str], None] = 'd5f8a2b3c4e6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("threads", sa.Column("connectors", postgresql.JSONB, nullable=False, server_default="[]"))


def downgrade() -> None:
    op.drop_column("threads", "connectors")
