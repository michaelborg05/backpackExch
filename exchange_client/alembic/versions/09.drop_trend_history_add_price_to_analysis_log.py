"""drop_trend_history_add_price_to_analysis_log

Revision ID: a1b2c3d4e5f6
Revises: ca9c81038442
Create Date: 2026-04-03

- Adds `price` column to trend_analysis_log (live price at time of signal)
- Drops the now-redundant trend_history table
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, Sequence[str], None] = 'ca9c81038442'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('trend_analysis_log', sa.Column('price', sa.Float(), nullable=True))
    op.drop_table('trend_history')


def downgrade() -> None:
    op.drop_column('trend_analysis_log', 'price')
    op.create_table(
        'trend_history',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('symbol', sa.String(), nullable=False),
        sa.Column('timeframe', sa.String(), nullable=False),
        sa.Column('trend_data', sa.JSON(), nullable=False),
        sa.Column('price', sa.Float(), nullable=False),
        sa.Column('rsi', sa.Float(), nullable=False),
        sa.Column('ema20', sa.Float(), nullable=False),
        sa.Column('ema50', sa.Float(), nullable=False),
        sa.Column('vwap', sa.Float(), nullable=True),
        sa.Column('volume_ratio', sa.Float(), nullable=True),
        sa.Column('adx', sa.Float(), nullable=True),
        sa.Column('indicators_changed', sa.Boolean(), default=True),
        sa.Column('data_timestamp', sa.DateTime(timezone=True), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint('symbol', 'timeframe', 'data_timestamp', name='uq_trend_history_entry'),
    )
    op.create_index(
        'ix_trend_history_symbol_timeframe_timestamp',
        'trend_history',
        ['symbol', 'timeframe', 'data_timestamp'],
    )
