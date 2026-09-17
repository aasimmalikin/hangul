"""episodes: title + active

Episodes now double as the user's chat history (the "Chats" rail), so each
needs a human-readable title and the same deactivate-don't-delete flag as
user_memory: a chat the user removes is hidden from them and from
recall_episodes, but the row is kept.

Revision ID: b3d9e1f2c4a5
Revises: 7a1c2e9d4b10
Create Date: 2026-09-17 18:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b3d9e1f2c4a5'
down_revision: Union[str, Sequence[str], None] = '7a1c2e9d4b10'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("episodes", sa.Column("title", sa.String(200), nullable=False, server_default=""))
    op.add_column("episodes", sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()))
    op.add_column("episodes", sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False))
    # one episode per conversation per user: a continued chat updates its row
    op.create_unique_constraint("uq_episodes_user_thread", "episodes", ["user_id", "thread_id"])


def downgrade() -> None:
    op.drop_constraint("uq_episodes_user_thread", "episodes", type_="unique")
    op.drop_column("episodes", "updated_at")
    op.drop_column("episodes", "active")
    op.drop_column("episodes", "title")
