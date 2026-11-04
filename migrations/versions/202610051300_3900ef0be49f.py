"""Add operate_as_ea to company

Revision ID: 3900ef0be49f
Revises: f79276dec27c
Create Date: 2026-10-05 13:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '3900ef0be49f'
down_revision: Union[str, Sequence[str], None] = 'f79276dec27c'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        'company',
        sa.Column('operate_as_ea', sa.Boolean(), nullable=False, server_default=sa.text('false')),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('company', 'operate_as_ea')
