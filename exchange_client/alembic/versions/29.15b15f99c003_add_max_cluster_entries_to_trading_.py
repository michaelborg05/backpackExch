"""add max_cluster_entries to trading_profiles

Revision ID: 15b15f99c003
Revises: 565eab56e406
Create Date: 2026-06-27 12:43:08.850638

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '15b15f99c003'
down_revision: Union[str, Sequence[str], None] = '565eab56e406'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('trading_profiles', sa.Column('max_cluster_entries', sa.Integer(), nullable=True))
    op.execute("UPDATE trading_profiles SET max_cluster_entries = 2 WHERE max_cluster_entries IS NULL")


def downgrade() -> None:
    op.drop_column('trading_profiles', 'max_cluster_entries')
