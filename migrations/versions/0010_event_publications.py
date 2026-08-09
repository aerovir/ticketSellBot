"""0010_event_publications: публикации события в цели (placements)

Одно событие может быть опубликовано в N мест: TG-канал, VK-группа (стена).
UNIQUE(event_id, platform, target_type, target_id) — идемпотентная фиксация.

Revision ID: 0010
Revises: 0009
Create Date: 2026-08-09

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '0010'
down_revision: Union[str, None] = '0009'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "event_publications",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("event_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("events.id", ondelete="CASCADE"), nullable=False),
        sa.Column("platform", sa.Enum("telegram", "vk", "max", name="platformtype", create_type=False), nullable=False),
        sa.Column("target_type", sa.String(32), nullable=False),
        sa.Column("target_id", sa.String(128), nullable=False),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("status", sa.String(16), nullable=False, server_default="posted"),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_event_publications_event_id", "event_publications", ["event_id"])
    op.create_unique_constraint(
        "uq_event_publication", "event_publications",
        ["event_id", "platform", "target_type", "target_id"],
    )


def downgrade() -> None:
    op.drop_constraint("uq_event_publication", "event_publications", type_="unique")
    op.drop_index("ix_event_publications_event_id", table_name="event_publications")
    op.drop_table("event_publications")
