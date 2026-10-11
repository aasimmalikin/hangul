"""businesses, business_days, business_events: How's business (harness.sales)

Revision ID: b0c1d2e3f4a6
Revises: a9b0c1d2e3f5
Create Date: 2026-10-08 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


# revision identifiers, used by Alembic.
revision: str = 'b0c1d2e3f4a6'
down_revision: Union[str, Sequence[str], None] = 'a9b0c1d2e3f5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "businesses",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.Integer, nullable=False, index=True),
        sa.Column("name", sa.String(80), nullable=False),
        sa.Column("kind", sa.String(32), nullable=False, server_default="retail_shop"),
        sa.Column("city", sa.String(80), nullable=False, server_default=""),
        sa.Column("lat", sa.Numeric(9, 5), nullable=True),
        sa.Column("lon", sa.Numeric(9, 5), nullable=True),
        sa.Column("brand_id", sa.Integer, nullable=True),
        sa.Column("launch_plan_id", sa.Integer, nullable=True),
        sa.Column("nudges", sa.Boolean, nullable=False, server_default="true"),
        sa.Column("nudged", JSONB, nullable=False, server_default="[]"),
        sa.Column("active", sa.Boolean, nullable=False, server_default="true"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_table(
        "business_days",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("business_id", sa.Integer, nullable=False, index=True),
        sa.Column("day", sa.Date, nullable=False),
        sa.Column("sales", sa.Numeric(14, 2), nullable=False, server_default="0"),
        sa.Column("bills", sa.Integer, nullable=True),
        sa.Column("closed", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("partial", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("promo", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("source", sa.String(16), nullable=False, server_default="chat"),
        sa.Column("note", sa.String(200), nullable=False, server_default=""),
        sa.Column("rain_mm", sa.Numeric(6, 1), nullable=True),
        sa.Column("tmax", sa.Numeric(5, 1), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("business_id", "day", name="uq_business_day"),
    )
    op.create_table(
        "business_events",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("business_id", sa.Integer, nullable=False, index=True),
        sa.Column("day", sa.Date, nullable=False),
        sa.Column("kind", sa.String(24), nullable=False),
        sa.Column("detail", JSONB, nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("business_events")
    op.drop_table("business_days")
    op.drop_table("businesses")
