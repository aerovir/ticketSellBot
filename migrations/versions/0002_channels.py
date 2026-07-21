"""add channels table and channel_id to events

Revision ID: 0002
Revises: 0001
Create Date: 2026-07-11
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- channels ---
    op.create_table(
        "channels",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("telegram_channel_id", sa.String(255), nullable=False, unique=True),
        sa.Column("title", sa.String(255), nullable=True),
        sa.Column("admin_telegram_user_id", sa.String(255), nullable=False),
        sa.Column("is_subscription_active", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("subscription_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    # --- add channel_id to events (nullable initially for backfill) ---
    op.add_column(
        "events",
        sa.Column("channel_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("channels.id"), nullable=True),
    )
    op.create_index("ix_events_channel", "events", ["channel_id"])

    # --- create a legacy channel for existing events ---
    op.execute("""
        INSERT INTO channels (id, telegram_channel_id, title, admin_telegram_user_id, is_subscription_active)
        VALUES (gen_random_uuid(), '__legacy__', 'Legacy Default Channel', '0', true)
    """)

    # --- backfill all existing events into the legacy channel ---
    op.execute("""
        UPDATE events SET channel_id = (SELECT id FROM channels WHERE telegram_channel_id = '__legacy__')
    """)

    # --- make channel_id NOT NULL ---
    op.alter_column("events", "channel_id", nullable=False)


def downgrade() -> None:
    # Drop FK and column
    op.drop_index("ix_events_channel", table_name="events")
    op.drop_constraint(
        # Alembic names FKs as "events_channel_id_fkey" by convention
        "events_channel_id_fkey",
        "events",
        type_="foreignkey",
    )
    op.drop_column("events", "channel_id")

    # Drop channels table
    op.drop_table("channels")
