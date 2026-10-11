"""brands: per-user brand looks, bought brand slots, and the brand a conversation uses

Revision ID: c1d2e3f4a5b6
Revises: d6e7f8a9b0c1
Create Date: 2026-10-06 22:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'c1d2e3f4a5b6'
down_revision: Union[str, Sequence[str], None] = 'd6e7f8a9b0c1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "brands",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.Integer, nullable=False),
        sa.Column("name", sa.String(80), nullable=False),
        sa.Column("kind", sa.String(32), nullable=False, server_default=""),
        sa.Column("look", sa.String(48), nullable=False, server_default=""),
        sa.Column("colors", postgresql.JSONB, nullable=False, server_default="[]"),
        sa.Column("style", sa.String(300), nullable=False, server_default=""),
        sa.Column("voice", sa.String(300), nullable=False, server_default=""),
        sa.Column("font", sa.String(32), nullable=False, server_default="sans"),
        sa.Column("logo", sa.String(200), nullable=False, server_default=""),
        sa.Column("active", sa.Boolean, nullable=False, server_default="true"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_brands_user_id", "brands", ["user_id"])
    op.add_column("users", sa.Column("extra_brands", sa.Integer, nullable=False, server_default="0"))
    op.add_column("conversations", sa.Column("brand_id", sa.Integer, nullable=True))


def downgrade() -> None:
    op.drop_column("conversations", "brand_id")
    op.drop_column("users", "extra_brands")
    op.drop_index("ix_brands_user_id", table_name="brands")
    op.drop_table("brands")
