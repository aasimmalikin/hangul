"""users.plan_region / plan_interval: Indian vs international pricing, monthly vs yearly

Revision ID: b8c9d0e1f2a3
Revises: a7b8c9d0e1f2
Create Date: 2026-10-03 16:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b8c9d0e1f2a3'
down_revision: Union[str, Sequence[str], None] = 'a7b8c9d0e1f2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("users", sa.Column("plan_region", sa.String(8), nullable=False, server_default="intl"))
    op.add_column("users", sa.Column("plan_interval", sa.String(8), nullable=False, server_default="month"))


def downgrade() -> None:
    op.drop_column("users", "plan_interval")
    op.drop_column("users", "plan_region")
