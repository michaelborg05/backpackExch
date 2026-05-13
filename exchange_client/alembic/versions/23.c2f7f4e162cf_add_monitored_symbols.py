"""add_monitored_symbols

Revision ID: c2f7f4e162cf
Revises: 690611d3d9b4
Create Date: 2026-05-13 21:51:33.970754

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c2f7f4e162cf'
down_revision: Union[str, Sequence[str], None] = '690611d3d9b4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'monitored_symbols',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('symbol', sa.String(), nullable=False),
        sa.Column('enabled', sa.Boolean(), nullable=False, server_default=sa.text('true')),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index('ix_monitored_symbols_symbol', 'monitored_symbols', ['symbol'], unique=True)

    # Seed from distinct symbols already in symbol_configs
    op.execute("""
        INSERT INTO monitored_symbols (symbol, enabled)
        SELECT DISTINCT symbol, true
        FROM symbol_configs
        ON CONFLICT DO NOTHING
    """)


def downgrade() -> None:
    op.drop_index('ix_monitored_symbols_symbol', table_name='monitored_symbols')
    op.drop_table('monitored_symbols')
