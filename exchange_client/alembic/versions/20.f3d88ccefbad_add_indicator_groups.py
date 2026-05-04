"""add_indicator_groups

Revision ID: f3d88ccefbad
Revises: fa6a968f35dd
Create Date: 2026-05-01 13:29:45.968172

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'f3d88ccefbad'
down_revision: Union[str, Sequence[str], None] = 'fa6a968f35dd'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('indicators', sa.Column('indicator_group', sa.String(length=64), nullable=True))
    op.add_column('trading_profiles', sa.Column('trend_indicator_groups', postgresql.JSONB(astext_type=sa.Text()), nullable=True))
    op.add_column('trading_profiles', sa.Column('entry_indicator_groups', postgresql.JSONB(astext_type=sa.Text()), nullable=True))


def downgrade() -> None:
    op.drop_column('trading_profiles', 'entry_indicator_groups')
    op.drop_column('trading_profiles', 'trend_indicator_groups')
    op.drop_column('indicators', 'indicator_group')
