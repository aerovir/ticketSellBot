"""0013_dynamic_pricing: динамические цены по дате (early bird, pro-фича)

Таблица event_price_ranges (диапазоны: starts_at/ends_at/price, привязаны к
событию). events.published_at — дата публикации (начало обязательного покрытия).
payments.price_range_label — снимок диапазона, по которому куплен билет.

Revision ID: 0013
Revises: 0012
Create Date: 2026-08-18

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '0013'
down_revision: Union[str, None] = '0012'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "event_price_ranges",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("event_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("events.id", ondelete="CASCADE"), nullable=False),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("price", sa.Numeric(precision=10, scale=2), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_event_price_ranges_event_id", "event_price_ranges", ["event_id"])
    # Аудит: какой диапазон применялся на платеже (nullable — исторические платежи)
    op.add_column("payments", sa.Column("price_range_label", sa.String(64), nullable=True))
    # Дата публикации — начало обязательного покрытия диапазонов
    op.add_column("events", sa.Column("published_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("events", "published_at")
    op.drop_column("payments", "price_range_label")
    op.drop_index("ix_event_price_ranges_event_id", table_name="event_price_ranges")
    op.drop_table("event_price_ranges")
