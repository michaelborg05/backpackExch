"""add_sl_tp_cooldown_minutes_to_profiles

Revision ID: 690611d3d9b4
Revises: 3b060a94bd55
Create Date: 2026-05-05 19:35:27.991671

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '690611d3d9b4'
down_revision: Union[str, Sequence[str], None] = '3b060a94bd55'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Rename signal_cooldown_seconds → signal_cooldown_minutes, converting existing values (seconds ÷ 60)
    op.add_column('trading_profiles', sa.Column('sl_cooldown_minutes', sa.Integer(), nullable=True))
    op.add_column('trading_profiles', sa.Column('tp_cooldown_minutes', sa.Integer(), nullable=True))
    op.add_column('trading_profiles', sa.Column('signal_cooldown_minutes', sa.Integer(), nullable=True))
    op.execute("UPDATE trading_profiles SET signal_cooldown_minutes = COALESCE(signal_cooldown_seconds / 60, 15)")
    op.execute("UPDATE trading_profiles SET sl_cooldown_minutes = COALESCE(signal_cooldown_seconds / 60, 15)")
    op.execute("UPDATE trading_profiles SET tp_cooldown_minutes = COALESCE(signal_cooldown_seconds / 60, 15)")
    op.alter_column('trading_profiles', 'signal_cooldown_minutes', nullable=False, server_default='15')
    op.drop_column('trading_profiles', 'signal_cooldown_seconds')

    # New per-profile post-trade cooldown overrides


def downgrade() -> None:
    op.drop_column('trading_profiles', 'tp_cooldown_minutes')
    op.drop_column('trading_profiles', 'sl_cooldown_minutes')

    op.add_column('trading_profiles', sa.Column('signal_cooldown_seconds', sa.Integer(), nullable=True))
    op.execute("UPDATE trading_profiles SET signal_cooldown_seconds = signal_cooldown_minutes * 60")
    op.drop_column('trading_profiles', 'signal_cooldown_minutes')
