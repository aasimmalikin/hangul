"""billing: plan columns on users + billing_events

Paid model access via Lemon Squeezy (harness.billing). The plan columns are
written only by the webhook; billing_events makes deliveries idempotent.

Revision ID: d7e8f9a0b1c2
Revises: c5d6e7f8a9b0
Create Date: 2026-10-01 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd7e8f9a0b1c2'
down_revision: Union[str, Sequence[str], None] = 'c5d6e7f8a9b0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("users", sa.Column("plan", sa.String(16), nullable=False, server_default="free"))
    op.add_column("users", sa.Column("plan_status", sa.String(16), nullable=True))
    op.add_column("users", sa.Column("plan_period_start", sa.DateTime(timezone=True), nullable=True))
    op.add_column("users", sa.Column("plan_renews_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("users", sa.Column("plan_ends_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("users", sa.Column("ls_customer_id", sa.String(32), nullable=True))
    op.add_column("users", sa.Column("ls_subscription_id", sa.String(32), nullable=True))
    op.add_column("users", sa.Column("ls_portal_url", sa.Text, nullable=True))
    op.create_index("ix_users_ls_subscription_id", "users", ["ls_subscription_id"])
    op.create_table(
        "billing_events",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("event_name", sa.String(64), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("billing_events")
    op.drop_index("ix_users_ls_subscription_id", table_name="users")
    for col in ("ls_portal_url", "ls_subscription_id", "ls_customer_id", "plan_ends_at",
                "plan_renews_at", "plan_period_start", "plan_status", "plan"):
        op.drop_column("users", col)
