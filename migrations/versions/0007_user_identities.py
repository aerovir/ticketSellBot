"""0007_user_identities: каноническая идентичность организатора

Таблицы:
- user_identities — способы входа (TG/VK) → канонический users.id (UNIQUE platform+platform_user_id)
- link_codes — одноразовые коды привязки площадок (organizer-only)

Backfill: каждый существующий users получает identity (platform, platform_user_id)
с DISTINCT ON — users не имел unique constraint на эту пару.

Revision ID: 0007
Revises: 0006
Create Date: 2026-08-09

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '0007'
down_revision: Union[str, None] = '0006'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ─── user_identities ────────────────────────────────────────
    # create_type=False: enum platformtype уже существует (0001).
    op.create_table(
        "user_identities",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("platform", sa.Enum("telegram", "vk", "max", name="platformtype", create_type=False), nullable=False),
        sa.Column("platform_user_id", sa.String(255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_user_identities_user_id", "user_identities", ["user_id"])
    op.create_unique_constraint(
        "uq_user_identity_platform_puid", "user_identities", ["platform", "platform_user_id"],
    )

    # ─── link_codes ─────────────────────────────────────────────
    op.create_table(
        "link_codes",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("code", sa.String(16), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("target_platform", sa.Enum("telegram", "vk", "max", name="platformtype", create_type=False), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_link_codes_code", "link_codes", ["code"], unique=True)

    # ─── Backfill: identity для всех существующих users ─────────
    op.execute("""
        INSERT INTO user_identities (id, user_id, platform, platform_user_id, created_at)
        SELECT DISTINCT ON (platform, platform_user_id)
               gen_random_uuid(), id, platform, platform_user_id, now()
        FROM users
        ORDER BY platform, platform_user_id
    """)


def downgrade() -> None:
    op.drop_index("ix_link_codes_code", table_name="link_codes")
    op.drop_table("link_codes")
    op.drop_constraint("uq_user_identity_platform_puid", "user_identities", type_="unique")
    op.drop_index("ix_user_identities_user_id", table_name="user_identities")
    op.drop_table("user_identities")
