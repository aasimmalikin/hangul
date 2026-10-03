"""user_settings.onboarded: the first-run walkthrough was finished or skipped

Existing rows are marked onboarded (they already use the app); new users
start at false and see the three-step walkthrough once.

Revision ID: d3e4f5a6b7c8
Revises: c2d3e4f5a6b7
Create Date: 2026-10-03 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd3e4f5a6b7c8'
down_revision: Union[str, Sequence[str], None] = 'c2d3e4f5a6b7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # true for everyone already here, then false as the default for new rows
    op.add_column("user_settings", sa.Column("onboarded", sa.Boolean, nullable=False, server_default=sa.true()))
    op.alter_column("user_settings", "onboarded", server_default=sa.false())


def downgrade() -> None:
    op.drop_column("user_settings", "onboarded")
