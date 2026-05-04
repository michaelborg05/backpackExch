"""drop_signal_timeframe

Revision ID: 3b060a94bd55
Revises: f3d88ccefbad
Create Date: 2026-05-04 12:48:43.323356

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '3b060a94bd55'
down_revision: Union[str, Sequence[str], None] = 'f3d88ccefbad'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_column('trading_profiles', 'signal_timeframe')
    op.drop_column('trading_profiles', 'max_risk_pct')


def downgrade() -> None:
    op.add_column('trading_profiles', sa.Column('max_risk_pct', sa.Numeric(), nullable=True))
    op.add_column('trading_profiles', sa.Column('signal_timeframe', sa.String(), nullable=True))
