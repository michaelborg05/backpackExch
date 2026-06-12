"""add exit indicators support

Revision ID: b7c8d9e0f1a2
Revises: a3b4c5d6e7f8
Create Date: 2026-06-02
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = 'b7c8d9e0f1a2'
down_revision = 'a3b4c5d6e7f8'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('trading_profiles', sa.Column('min_exit_indicators_required', sa.Integer(), server_default='2', nullable=False))
    op.add_column('trading_profiles', sa.Column('exit_indicator_groups', JSONB(), nullable=True))
    op.add_column('trading_profiles', sa.Column('exit_timeframe', sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column('trading_profiles', 'exit_timeframe')
    op.drop_column('trading_profiles', 'exit_indicator_groups')
    op.drop_column('trading_profiles', 'min_exit_indicators_required')
