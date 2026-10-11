"""customers (the shop's own customer list); waitlist.trade and waitlist.city

Revision ID: e5f6a7b8c9d1
Revises: d4e5f6a7b8c0
Create Date: 2026-10-10 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e5f6a7b8c9d1'
down_revision: Union[str, Sequence[str], None] = 'd4e5f6a7b8c0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "customers",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.Integer, nullable=False),
        sa.Column("business_id", sa.Integer, nullable=True),
        sa.Column("name", sa.String(80), nullable=False),
        sa.Column("phone", sa.String(20), nullable=False, server_default=""),
        sa.Column("birth_month", sa.Integer, nullable=True),
        sa.Column("birth_day", sa.Integer, nullable=True),
        sa.Column("birth_year", sa.Integer, nullable=True),
        sa.Column("note", sa.String(200), nullable=False, server_default=""),
        sa.Column("visits", sa.Integer, nullable=False, server_default="0"),
        sa.Column("last_visit", sa.Date, nullable=True),
        sa.Column("active", sa.Boolean, nullable=False, server_default="true"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("conversation_id", sa.String(32), nullable=True),
        sa.Column("said", sa.String(500), nullable=True),
    )
    op.create_index("ix_customers_user_id", "customers", ["user_id"])
    op.add_column("waitlist", sa.Column("trade", sa.String(16), nullable=False, server_default=""))
    op.add_column("waitlist", sa.Column("city", sa.String(80), nullable=False, server_default=""))


def downgrade() -> None:
    op.drop_column("waitlist", "city")
    op.drop_column("waitlist", "trade")
    op.drop_index("ix_customers_user_id", table_name="customers")
    op.drop_table("customers")
