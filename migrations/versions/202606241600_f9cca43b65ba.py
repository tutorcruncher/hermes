"""Add receive_marketing_emails to company

Revision ID: f9cca43b65ba
Revises: e4e0a0696f1f
Create Date: 2026-06-24 16:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f9cca43b65ba'
down_revision: Union[str, Sequence[str], None] = 'e4e0a0696f1f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        'company',
        sa.Column('receive_marketing_emails', sa.Boolean(), nullable=False, server_default=sa.text('false')),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('company', 'receive_marketing_emails')
