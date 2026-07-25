"""remove_atr_column

Revision ID: 192ec64e0046
Revises: 19c1389b6275
Create Date: 2026-07-25 16:20:18.834331

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '192ec64e0046'
down_revision: Union[str, Sequence[str], None] = '19c1389b6275'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_column('trading_profiles', 'use_atr_filter')


def downgrade() -> None:
    op.add_column('trading_profiles', sa.Column('use_atr_filter', sa.Boolean(), server_default=sa.text('false'), nullable=True))

