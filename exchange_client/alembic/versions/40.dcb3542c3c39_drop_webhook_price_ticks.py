"""drop webhook_price_ticks

The table held a ~2-minute price sample used as the backtester's intra-candle
fill path. It was superseded by price_path_shadow (1m OHLC expanded to an
O/H/L/C path: 60 points per 15m bar instead of ~7.5, backfillable for years and
covering every symbol). Nothing has written to it since 2026-07-26 and both
backtest runners already default to tick_source='path1m', so the remaining
446k rows / 48 MB are dead weight.

Downgrade recreates the (empty) table structure only — the sampled prices are
not recoverable, and price_path_shadow supersedes them anyway.

Revision ID: dcb3542c3c39
Revises: d4e8b217a9c3
Create Date: 2026-08-18 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'dcb3542c3c39'
down_revision: Union[str, Sequence[str], None] = 'd4e8b217a9c3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_index(op.f('ix_webhook_price_ticks_timestamp'), table_name='webhook_price_ticks')
    op.drop_index(op.f('ix_webhook_price_ticks_symbol'), table_name='webhook_price_ticks')
    op.drop_table('webhook_price_ticks')


def downgrade() -> None:
    op.create_table(
        'webhook_price_ticks',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('symbol', sa.String(), nullable=False),
        sa.Column('timestamp', sa.DateTime(timezone=True), nullable=False),
        sa.Column('price', sa.Numeric(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_webhook_price_ticks_symbol'), 'webhook_price_ticks',
                    ['symbol'], unique=False)
    op.create_index(op.f('ix_webhook_price_ticks_timestamp'), 'webhook_price_ticks',
                    ['timestamp'], unique=False)
