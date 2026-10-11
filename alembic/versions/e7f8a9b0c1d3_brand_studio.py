"""brand studio: the brand kit fields, the photo library and posts (with captions and client review)

Revision ID: e7f8a9b0c1d3
Revises: c1d2e3f4a5b6
Create Date: 2026-10-07 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'e7f8a9b0c1d3'
down_revision: Union[str, Sequence[str], None] = 'c1d2e3f4a5b6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

KIT = (("logo_dark", 200), ("handle", 60), ("website", 200), ("cta", 60), ("footer", 120))


def upgrade() -> None:
    for col, n in KIT:
        op.add_column("brands", sa.Column(col, sa.String(n), nullable=False, server_default=""))
    op.add_column("brands", sa.Column("hashtags", postgresql.JSONB, nullable=False, server_default="[]"))
    op.create_table(
        "brand_assets",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("brand_id", sa.Integer, nullable=False),
        sa.Column("user_id", sa.Integer, nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("width", sa.Integer, nullable=False, server_default="0"),
        sa.Column("height", sa.Integer, nullable=False, server_default="0"),
        sa.Column("active", sa.Boolean, nullable=False, server_default="true"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_brand_assets_brand_id", "brand_assets", ["brand_id"])
    op.create_index("ix_brand_assets_user_id", "brand_assets", ["user_id"])
    op.create_table(
        "brand_posts",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("brand_id", sa.Integer, nullable=False),
        sa.Column("user_id", sa.Integer, nullable=False),
        sa.Column("kind", sa.String(16), nullable=False, server_default="single"),
        sa.Column("layout", sa.String(24), nullable=False, server_default="band"),
        sa.Column("words", postgresql.JSONB, nullable=False, server_default="{}"),
        sa.Column("slides", postgresql.JSONB, nullable=False, server_default="[]"),
        sa.Column("sizes", postgresql.JSONB, nullable=False, server_default="[]"),
        sa.Column("files", postgresql.JSONB, nullable=False, server_default="[]"),
        sa.Column("captions", postgresql.JSONB, nullable=False, server_default="{}"),
        sa.Column("review_status", sa.String(16), nullable=False, server_default="none"),
        sa.Column("review_comment", sa.Text, nullable=False, server_default=""),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("active", sa.Boolean, nullable=False, server_default="true"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_brand_posts_brand_id", "brand_posts", ["brand_id"])
    op.create_index("ix_brand_posts_user_id", "brand_posts", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_brand_posts_user_id", table_name="brand_posts")
    op.drop_index("ix_brand_posts_brand_id", table_name="brand_posts")
    op.drop_table("brand_posts")
    op.drop_index("ix_brand_assets_user_id", table_name="brand_assets")
    op.drop_index("ix_brand_assets_brand_id", table_name="brand_assets")
    op.drop_table("brand_assets")
    op.drop_column("brands", "hashtags")
    for col, _n in reversed(KIT):
        op.drop_column("brands", col)
