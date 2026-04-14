"""add_direction_and_market_type

Revision ID: 76d11a90f3ac
Revises: 90d636e1d4bd
Create Date: 2026-04-14 10:48:39.287940

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '76d11a90f3ac'
down_revision: Union[str, Sequence[str], None] = '90d636e1d4bd'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── trading_profiles: add market_type ─────────────────────────────
    op.add_column(
        'trading_profiles',
        sa.Column('market_type', sa.String(), nullable=True, server_default='SPOT')
    )

    # ── trades: add direction ─────────────────────────────────────────
    op.add_column(
        'trades',
        sa.Column('direction', sa.String(), nullable=True)
    )
    op.create_check_constraint(
        'valid_trade_direction',
        'trades',
        "direction IN ('LONG', 'SHORT') OR direction IS NULL"
    )

    # ── positions: add direction ───────────────────────────────────────
    op.add_column(
        'positions',
        sa.Column('direction', sa.String(), nullable=True, server_default='LONG')
    )
    op.create_check_constraint(
        'valid_position_direction',
        'positions',
        "direction IN ('LONG', 'SHORT') OR direction IS NULL"
    )

    # ── positions: rename buy_trade_id → entry_trade_id ───────────────
    op.alter_column('positions', 'buy_trade_id', new_column_name='entry_trade_id')

    # ── positions: rename sell_trade_id → exit_trade_id ──────────────
    op.alter_column('positions', 'sell_trade_id', new_column_name='exit_trade_id')


def downgrade() -> None:
    # Reverse column renames
    op.alter_column('positions', 'entry_trade_id', new_column_name='buy_trade_id')
    op.alter_column('positions', 'exit_trade_id', new_column_name='sell_trade_id')

    # Drop constraints
    op.drop_constraint('valid_position_direction', 'positions', type_='check')
    op.drop_constraint('valid_trade_direction', 'trades', type_='check')

    # Drop columns
    op.drop_column('positions', 'direction')
    op.drop_column('trades', 'direction')
    op.drop_column('trading_profiles', 'market_type')
