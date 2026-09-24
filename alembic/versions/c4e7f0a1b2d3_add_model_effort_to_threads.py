"""add model and effort to threads

A run now records which model and reasoning effort it started with, so
/approve resumes the paused run with the same settings the user chose
instead of whatever the server default happens to be.

Revision ID: c4e7f0a1b2d3
Revises: b3d9e1f2c4a5
Create Date: 2026-09-18 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c4e7f0a1b2d3'
down_revision: Union[str, Sequence[str], None] = 'b3d9e1f2c4a5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("threads", sa.Column("model", sa.String(64), nullable=True))
    op.add_column("threads", sa.Column("effort", sa.String(16), nullable=True))


def downgrade() -> None:
    op.drop_column("threads", "effort")
    op.drop_column("threads", "model")
