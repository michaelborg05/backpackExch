"""add regime_timeframe override to trading_profiles

Revision ID: a8d4e7c92f10
Revises: f3e9c2a71b45
Create Date: 2026-07-12 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a8d4e7c92f10'
down_revision: Union[str, Sequence[str], None] = 'f3e9c2a71b45'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # NULL = strategy-based default (entry TF for mean reversion, trend TF otherwise).
    # Set to e.g. "240" to run the regime filter against the 4h timeframe.
    op.add_column('trading_profiles',
                  sa.Column('regime_timeframe', sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column('trading_profiles', 'regime_timeframe')
