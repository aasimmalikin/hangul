"""vault credentials and consents

The token vault: third-party secrets encrypted at rest (vault_credentials)
and standing per-provider permission for the agent to use them on a user's
behalf (vault_consents). Grants are short-lived and live in Redis only.

Revision ID: d5f8a2b3c4e6
Revises: c4e7f0a1b2d3
Create Date: 2026-09-18 14:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'd5f8a2b3c4e6'
down_revision: Union[str, Sequence[str], None] = 'c4e7f0a1b2d3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "vault_credentials",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.Integer, nullable=True),
        sa.Column("provider", sa.String(64), nullable=False),
        sa.Column("label", sa.String(128), nullable=False, server_default=""),
        sa.Column("kind", sa.String(16), nullable=False, server_default="api_key"),
        sa.Column("ciphertext", sa.String, nullable=False),
        sa.Column("fingerprint", sa.String(16), nullable=False),
        sa.Column("scopes", postgresql.JSONB, nullable=False, server_default="[]"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_vault_credentials_user_id", "vault_credentials", ["user_id"])
    op.create_index("ix_vault_credentials_provider", "vault_credentials", ["provider"])

    op.create_table(
        "vault_consents",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.Integer, nullable=False),
        sa.Column("provider", sa.String(64), nullable=False),
        sa.Column("credential_id", sa.Integer, nullable=True),
        sa.Column("allow_write", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("granted_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_vault_consents_user_id", "vault_consents", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_vault_consents_user_id", table_name="vault_consents")
    op.drop_table("vault_consents")
    op.drop_index("ix_vault_credentials_provider", table_name="vault_credentials")
    op.drop_index("ix_vault_credentials_user_id", table_name="vault_credentials")
    op.drop_table("vault_credentials")
