"""trading_hours_use_profile_id

Revision ID: f1e2d3c4b5a6
Revises: e7f8a9b0c1d2
Create Date: 2026-05-16 00:00:01.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'f1e2d3c4b5a6'
down_revision: Union[str, Sequence[str], None] = 'e7f8a9b0c1d2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add profile_id column (nullable first so we can populate it)
    op.add_column('profile_trading_hours', sa.Column('profile_id', sa.Integer(), nullable=True))

    # Populate from trading_profiles
    op.execute("""
        UPDATE profile_trading_hours th
        SET profile_id = tp.id
        FROM trading_profiles tp
        WHERE tp.name = th.profile_name
    """)

    # Delete any orphaned rows whose profile_name no longer matches a profile
    op.execute("DELETE FROM profile_trading_hours WHERE profile_id IS NULL")

    # Make NOT NULL and add FK
    op.alter_column('profile_trading_hours', 'profile_id', nullable=False)
    op.create_foreign_key(
        'fk_profile_trading_hours_profile_id',
        'profile_trading_hours', 'trading_profiles',
        ['profile_id'], ['id'],
        ondelete='CASCADE',
    )

    # Swap index
    op.drop_index('ix_profile_trading_hours_profile', table_name='profile_trading_hours')
    op.create_index('ix_profile_trading_hours_profile_id', 'profile_trading_hours', ['profile_id'])

    # Drop old string column
    op.drop_column('profile_trading_hours', 'profile_name')


def downgrade() -> None:
    op.add_column('profile_trading_hours', sa.Column('profile_name', sa.String(), nullable=True))
    op.execute("""
        UPDATE profile_trading_hours th
        SET profile_name = tp.name
        FROM trading_profiles tp
        WHERE tp.id = th.profile_id
    """)
    op.alter_column('profile_trading_hours', 'profile_name', nullable=False)
    op.drop_index('ix_profile_trading_hours_profile_id', table_name='profile_trading_hours')
    op.create_index('ix_profile_trading_hours_profile', 'profile_trading_hours', ['profile_name'])
    op.drop_constraint('fk_profile_trading_hours_profile_id', 'profile_trading_hours', type_='foreignkey')
    op.drop_column('profile_trading_hours', 'profile_id')
