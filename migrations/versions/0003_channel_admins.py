"""add channel_admins table for multi-admin per channel

Revision ID: 0003
Revises: 0002
Create Date: 2026-07-18
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0003"
down_revision: Union[str, None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- create channel_admins table ---
    op.create_table(
        "channel_admins",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("channel_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("channels.id", ondelete="CASCADE"), nullable=False),
        sa.Column("telegram_user_id", sa.String(255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("channel_id", "telegram_user_id", name="uq_channel_admin"),
    )

    # --- migrate existing admins from legacy field ---
    op.execute("""
        INSERT INTO channel_admins (id, channel_id, telegram_user_id, created_at)
        SELECT gen_random_uuid(), id, admin_telegram_user_id, created_at
        FROM channels
        WHERE admin_telegram_user_id != '' AND admin_telegram_user_id != '0'
    """)


def downgrade() -> None:
    op.drop_table("channel_admins")
