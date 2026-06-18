"""add_webhook_price_ticks

Revision ID: 565eab56e406
Revises: b7c8d9e0f1a2
Create Date: 2026-06-18 09:25:10.099746

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '565eab56e406'
down_revision: Union[str, Sequence[str], None] = 'b7c8d9e0f1a2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('webhook_price_ticks',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('symbol', sa.String(), nullable=False),
        sa.Column('timestamp', sa.DateTime(timezone=True), nullable=False),
        sa.Column('price', sa.Numeric(), nullable=False),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_webhook_price_ticks_symbol'), 'webhook_price_ticks', ['symbol'], unique=False)
    op.create_index(op.f('ix_webhook_price_ticks_timestamp'), 'webhook_price_ticks', ['timestamp'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_webhook_price_ticks_timestamp'), table_name='webhook_price_ticks')
    op.drop_index(op.f('ix_webhook_price_ticks_symbol'), table_name='webhook_price_ticks')
    op.drop_table('webhook_price_ticks')
