"""0012_promo_codes: скидки-промокоды на билеты (pro-фича)

Таблица promo_codes (привязана к событию event_id, код уникален в рамках
события). Новый enum discounttype (percent/fixed). В payments добавлены
base_amount / discount_amount / promo_code (nullable) — «сколько было бы без
скидки», «размер скидки», «применённый код». amount остаётся фактически
уплаченной суммой (уже со скидкой).

Revision ID: 0012
Revises: 0011
Create Date: 2026-08-17

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '0012'
down_revision: Union[str, None] = '0011'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "promo_codes",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("event_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("events.id", ondelete="CASCADE"), nullable=False),
        sa.Column("code", sa.String(64), nullable=False),
        sa.Column("discount_type", sa.Enum("percent", "fixed", name="discounttype"), nullable=False),
        sa.Column("discount_value", sa.Numeric(precision=10, scale=2), nullable=False),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("max_uses", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("used_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_promo_codes_event_id", "promo_codes", ["event_id"])
    op.create_unique_constraint("uq_promo_code_event_code", "promo_codes", ["event_id", "code"])

    # Поля применения промокода на платеже (nullable — исторические платежи)
    op.add_column("payments", sa.Column("base_amount", sa.Numeric(precision=10, scale=2), nullable=True))
    op.add_column("payments", sa.Column("discount_amount", sa.Numeric(precision=10, scale=2), nullable=True))
    op.add_column("payments", sa.Column("promo_code", sa.String(64), nullable=True))
    # Backfill: для старых платежей базовая сумма = amount, скидки не было
    op.execute("UPDATE payments SET base_amount = amount, discount_amount = 0 WHERE base_amount IS NULL")


def downgrade() -> None:
    op.drop_column("payments", "promo_code")
    op.drop_column("payments", "discount_amount")
    op.drop_column("payments", "base_amount")
    op.drop_constraint("uq_promo_code_event_code", "promo_codes", type_="unique")
    op.drop_index("ix_promo_codes_event_id", table_name="promo_codes")
    op.drop_table("promo_codes")
    op.execute("DROP TYPE IF EXISTS discounttype")
