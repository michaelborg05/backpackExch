"""19.trade_signal_snapshot

Replace trades.reason_summary with signal_snapshot JSON column.
Drop trade_validation_results table entirely.

Revision ID: a1b2c3d4e5f6
Revises: fef960dbb682
Create Date: 2026-04-23

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, Sequence[str], None] = 'fef960dbb682'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_column('trades', 'reason_summary')
    op.add_column('trades', sa.Column('signal_snapshot', postgresql.JSON(astext_type=sa.Text()), nullable=True))
    op.drop_table('trade_validation_results')


def downgrade() -> None:
    op.add_column('trades', sa.Column('reason_summary', postgresql.JSON(astext_type=sa.Text()), nullable=True))
    op.drop_column('trades', 'signal_snapshot')
    op.create_table(
        'trade_validation_results',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('trade_id', sa.Integer(), sa.ForeignKey('trades.id'), nullable=False),
        sa.Column('profile_name', sa.String(), nullable=False),
        sa.Column('side', sa.String(), nullable=True),
        sa.Column('symbol', sa.String(), nullable=False),
        sa.Column('validation_summary', sa.String(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_trade_validation_results_trade', 'trade_validation_results', ['trade_id'])
