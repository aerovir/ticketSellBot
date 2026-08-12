"""0011_event_upgrades: per-event премиум (единовременная оплата)

Одна запись на событие (event_id UNIQUE). Даёт pro-фичи (paid_events,
qr_codes, invite_tickets) для конкретного события, независимо от подписки.
expires_at = event.date. Переиспользует enum paymentstatus из 0001.

Revision ID: 0011
Revises: 0010
Create Date: 2026-08-12

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '0011'
down_revision: Union[str, None] = '0010'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "event_upgrades",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("event_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("events.id", ondelete="CASCADE"), nullable=False),
        sa.Column("amount", sa.Numeric(precision=10, scale=2), nullable=False, server_default="0"),
        sa.Column("status", sa.Enum("pending", "completed", "failed", "refunded", name="paymentstatus", create_type=False), nullable=False, server_default="completed"),
        sa.Column("provider", sa.String(32), nullable=True),
        sa.Column("payload", sa.Text(), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_event_upgrades_event_id", "event_upgrades", ["event_id"])
    op.create_unique_constraint("uq_event_upgrade", "event_upgrades", ["event_id"])


def downgrade() -> None:
    op.drop_constraint("uq_event_upgrade", "event_upgrades", type_="unique")
    op.drop_index("ix_event_upgrades_event_id", table_name="event_upgrades")
    op.drop_table("event_upgrades")
