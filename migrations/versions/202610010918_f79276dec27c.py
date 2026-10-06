"""Index contact email ignoring case

Revision ID: f79276dec27c
Revises: db904463c385
Create Date: 2026-10-01 09:18:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f79276dec27c'
down_revision: Union[str, Sequence[str], None] = 'db904463c385'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_index('ix_contact_email_lower', 'contact', [sa.text('lower(email)')])


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_contact_email_lower', table_name='contact')
