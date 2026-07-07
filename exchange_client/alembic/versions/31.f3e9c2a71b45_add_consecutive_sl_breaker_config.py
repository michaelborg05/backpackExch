"""add consecutive stop-loss breaker config to circuit_breaker_config

Revision ID: f3e9c2a71b45
Revises: 7c2a9f4e1b6d
Create Date: 2026-07-05 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f3e9c2a71b45'
down_revision: Union[str, Sequence[str], None] = '7c2a9f4e1b6d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # NULL/0 = consecutive-SL breaker disabled for the profile
    op.add_column('circuit_breaker_config',
                  sa.Column('max_consecutive_stop_losses', sa.Integer(), nullable=True))
    op.add_column('circuit_breaker_config',
                  sa.Column('consecutive_sl_lock_hours', sa.Integer(),
                            server_default='24', nullable=True))


def downgrade() -> None:
    op.drop_column('circuit_breaker_config', 'consecutive_sl_lock_hours')
    op.drop_column('circuit_breaker_config', 'max_consecutive_stop_losses')
