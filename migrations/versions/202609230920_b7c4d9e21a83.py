"""Signup attribution columns on company

Revision ID: b7c4d9e21a83
Revises: 5d51f946e024
Create Date: 2026-09-23 09:20:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel


# revision identifiers, used by Alembic.
revision: str = 'b7c4d9e21a83'
down_revision: Union[str, Sequence[str], None] = '5d51f946e024'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

COLUMNS = (
    'utm_medium',
    'utm_term',
    'utm_content',
    'ga4_client_id',
    'signup_email',
    'signup_phone',
    'signup_company_name',
)


def upgrade() -> None:
    """Upgrade schema."""
    for column in COLUMNS:
        op.add_column('company', sa.Column(column, sqlmodel.sql.sqltypes.AutoString(length=255), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    for column in reversed(COLUMNS):
        op.drop_column('company', column)
