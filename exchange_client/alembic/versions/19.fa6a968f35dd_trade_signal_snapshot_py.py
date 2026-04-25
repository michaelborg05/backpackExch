"""19.trade_signal_snapshot.py

Revision ID: fa6a968f35dd
Revises: fef960dbb682
Create Date: 2026-04-24 19:02:24.676060

"""
from typing import Sequence, Union
from sqlalchemy.dialects import postgresql

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'fa6a968f35dd'
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
