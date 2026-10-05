"""Merge the signup contact columns branch back into the main migration chain

Revision ID: db904463c385
Revises: f9cca43b65ba, b7c4d9e21a83
Create Date: 2026-09-30 13:00:00.000000

"""

from typing import Sequence, Union

# revision identifiers, used by Alembic.
revision: str = 'db904463c385'
down_revision: Union[str, Sequence[str], None] = ('f9cca43b65ba', 'b7c4d9e21a83')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
