"""billing: move from Lemon Squeezy to Dodo Payments

Provider-neutral names for the customer / subscription ids; the portal URL is
no longer stored (Dodo mints a short-lived link on demand). billing_events ids
are now the provider's `webhook-id`.

Revision ID: e8f9a0b1c2d3
Revises: d7e8f9a0b1c2
Create Date: 2026-10-01 18:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e8f9a0b1c2d3'
down_revision: Union[str, Sequence[str], None] = 'd7e8f9a0b1c2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_index("ix_users_ls_subscription_id", table_name="users")
    op.alter_column("users", "ls_customer_id", new_column_name="billing_customer_id",
                    type_=sa.String(64), existing_type=sa.String(32), existing_nullable=True)
    op.alter_column("users", "ls_subscription_id", new_column_name="billing_subscription_id",
                    type_=sa.String(64), existing_type=sa.String(32), existing_nullable=True)
    op.drop_column("users", "ls_portal_url")
    op.create_index("ix_users_billing_subscription_id", "users", ["billing_subscription_id"])
    op.create_index("ix_users_billing_customer_id", "users", ["billing_customer_id"])
    op.alter_column("billing_events", "id", type_=sa.String(128), existing_type=sa.String(64))


def downgrade() -> None:
    op.alter_column("billing_events", "id", type_=sa.String(64), existing_type=sa.String(128))
    op.drop_index("ix_users_billing_customer_id", table_name="users")
    op.drop_index("ix_users_billing_subscription_id", table_name="users")
    op.add_column("users", sa.Column("ls_portal_url", sa.Text, nullable=True))
    op.alter_column("users", "billing_subscription_id", new_column_name="ls_subscription_id",
                    type_=sa.String(32), existing_type=sa.String(64), existing_nullable=True)
    op.alter_column("users", "billing_customer_id", new_column_name="ls_customer_id",
                    type_=sa.String(32), existing_type=sa.String(64), existing_nullable=True)
    op.create_index("ix_users_ls_subscription_id", "users", ["ls_subscription_id"])
