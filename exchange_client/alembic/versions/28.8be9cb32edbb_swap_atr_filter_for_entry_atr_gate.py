"""drop the retired use_atr_filter column

The old ATR/ATR-SMA ratio filter (fed by exchange-candle API calls) is removed.
ATR volatility gating is now configured as an `atr_regime` indicator inside a
profile's trend_indicators / entry_indicators JSON (hard_stop), so no dedicated
profile columns are needed — this migration only drops the now-unused flag.

Revision ID: 8be9cb32edbb
Revises: b7c8d9e0f1a2
Create Date: 2026-07-24
"""
from alembic import op
import sqlalchemy as sa

revision = '8be9cb32edbb'
down_revision = 'b7c8d9e0f1a2'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_column('trading_profiles', 'use_atr_filter')


def downgrade() -> None:
    op.add_column('trading_profiles', sa.Column('use_atr_filter', sa.Boolean(), server_default=sa.text('false'), nullable=True))
