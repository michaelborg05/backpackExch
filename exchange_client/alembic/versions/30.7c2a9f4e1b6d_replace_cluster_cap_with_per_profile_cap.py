"""replace max_cluster_entries with max_open_positions_per_profile

Revision ID: 7c2a9f4e1b6d
Revises: 15b15f99c003
Create Date: 2026-07-03 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '7c2a9f4e1b6d'
down_revision: Union[str, Sequence[str], None] = '15b15f99c003'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('trading_profiles', sa.Column('max_open_positions_per_profile', sa.Integer(), nullable=True))
    op.drop_column('trading_profiles', 'max_cluster_entries')
    op.execute("UPDATE trading_profiles SET max_open_positions_per_profile = 2 WHERE max_open_positions_per_profile IS NULL")


def downgrade() -> None:
    op.add_column('trading_profiles', sa.Column('max_cluster_entries', sa.Integer(), nullable=True))
    op.execute("UPDATE trading_profiles SET max_cluster_entries = 2 WHERE max_cluster_entries IS NULL")
    op.drop_column('trading_profiles', 'max_open_positions_per_profile')
