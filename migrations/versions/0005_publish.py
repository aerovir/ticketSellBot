"""0005_publish: add is_published to events

Revision ID: 0005
Revises: 0004
Create Date: 2026-07-24 14:15:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0005'
down_revision: Union[str, None] = '0004'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('events', sa.Column(
        'is_published', sa.Boolean(),
        server_default=sa.text('true'),
        nullable=False,
    ))
    # server_default=true ensures existing rows stay "published"


def downgrade() -> None:
    op.drop_column('events', 'is_published')
