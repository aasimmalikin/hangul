"""waitlist: pre-registration before launch (/join)

Revision ID: f8a9b0c1d2e4
Revises: e7f8a9b0c1d3
Create Date: 2026-10-07 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f8a9b0c1d2e4'
down_revision: Union[str, Sequence[str], None] = 'e7f8a9b0c1d3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "waitlist",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("email", sa.String(254), nullable=False, unique=True),
        sa.Column("persona", sa.String(16), nullable=False, server_default=""),
        sa.Column("interest", sa.String(8), nullable=False, server_default=""),
        sa.Column("source", sa.String(40), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("waitlist")
