"""0008_event_managers: соработники мероприятия (несколько продавцов)

M2M event_managers(event_id, user_id) — UNIQUE(event_id, user_id).

Revision ID: 0008
Revises: 0007
Create Date: 2026-08-09

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '0008'
down_revision: Union[str, None] = '0007'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "event_managers",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("event_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("events.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_event_managers_event_id", "event_managers", ["event_id"])
    op.create_index("ix_event_managers_user_id", "event_managers", ["user_id"])
    op.create_unique_constraint("uq_event_manager", "event_managers", ["event_id", "user_id"])


def downgrade() -> None:
    op.drop_constraint("uq_event_manager", "event_managers", type_="unique")
    op.drop_index("ix_event_managers_user_id", table_name="event_managers")
    op.drop_index("ix_event_managers_event_id", table_name="event_managers")
    op.drop_table("event_managers")
