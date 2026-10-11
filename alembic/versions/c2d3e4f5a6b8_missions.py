"""missions, mission_trust: jobs Hangul carries through (harness.missions)

Revision ID: c2d3e4f5a6b8
Revises: b0c1d2e3f4a6
Create Date: 2026-10-07 18:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


# revision identifiers, used by Alembic.
revision: str = 'c2d3e4f5a6b8'
down_revision: Union[str, Sequence[str], None] = 'b0c1d2e3f4a6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "missions",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.Integer, nullable=False, index=True),
        sa.Column("kind", sa.String(24), nullable=False),
        sa.Column("business_id", sa.Integer, nullable=False, server_default="0"),
        sa.Column("target_day", sa.Date, nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="active"),
        sa.Column("steps", JSONB, nullable=False, server_default="[]"),
        sa.Column("data", JSONB, nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("user_id", "kind", "business_id", "target_day", name="uq_mission"),
    )
    op.create_index("ix_missions_status", "missions", ["status"])
    op.create_table(
        "mission_trust",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.Integer, nullable=False, index=True),
        sa.Column("scope", sa.String(48), nullable=False),
        sa.Column("streak", sa.Integer, nullable=False, server_default="0"),
        sa.Column("auto", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("offered", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("user_id", "scope", name="uq_mission_trust"),
    )


def downgrade() -> None:
    op.drop_table("mission_trust")
    op.drop_index("ix_missions_status", table_name="missions")
    op.drop_table("missions")
