"""0009_vk_groups: VK-группы как цели публикации (self-service организатора)

Таблица vk_groups: group_id (UNIQUE), community_token (зашифрованный),
owner_user_id FK users.

Revision ID: 0009
Revises: 0008
Create Date: 2026-08-09

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '0009'
down_revision: Union[str, None] = '0008'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "vk_groups",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("group_id", sa.String(64), nullable=False),
        sa.Column("title", sa.String(255), nullable=True),
        sa.Column("community_token", sa.Text(), nullable=True),
        sa.Column("owner_user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_vk_groups_group_id", "vk_groups", ["group_id"], unique=True)
    op.create_index("ix_vk_groups_owner", "vk_groups", ["owner_user_id"])


def downgrade() -> None:
    op.drop_index("ix_vk_groups_owner", table_name="vk_groups")
    op.drop_index("ix_vk_groups_group_id", table_name="vk_groups")
    op.drop_table("vk_groups")
