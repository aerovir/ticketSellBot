"""0015_event_age_restriction: возрастное ограничение мероприятия (ФЗ-436)

Знак информационной продукции (0+/6+/12+/16+/18+), который организатор
устанавливает при создании мероприятия и который отображается на афише,
странице мероприятия и билете.

Revision ID: 0015
Revises: 0014
Create Date: 2026-08-23

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '0015'
down_revision: Union[str, None] = '0014'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "events",
        sa.Column("age_restriction", sa.String(4), nullable=False, server_default="0+"),
    )


def downgrade() -> None:
    op.drop_column("events", "age_restriction")
