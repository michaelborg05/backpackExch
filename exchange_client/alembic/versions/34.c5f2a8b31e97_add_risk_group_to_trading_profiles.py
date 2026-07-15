"""add risk groups (shared position limits across profiles)

Adds a ``risk_group`` tag to trading_profiles and a ``risk_groups`` table that
holds the shared limits ONCE per group. Profiles sharing a tag share those
limits, so several timeframe-aligned profiles (e.g. three 4hr-trend/1hr-entry
longs) can't all pile into the same coin / the same macro move.

The tag is a loose reference (no FK) so a profile can carry a tag before its
group config row exists. NULL tag = ungrouped; NULL limit = no cap = existing
behaviour.

Revision ID: c5f2a8b31e97
Revises: b1c7e5a92d34
Create Date: 2026-07-15 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c5f2a8b31e97'
down_revision: Union[str, Sequence[str], None] = 'b1c7e5a92d34'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('trading_profiles',
                  sa.Column('risk_group', sa.String(), nullable=True))

    op.create_table(
        'risk_groups',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('name', sa.String(), nullable=False),
        sa.Column('max_open_positions', sa.Integer(), nullable=True),
        sa.Column('max_positions_per_symbol', sa.Integer(), nullable=True),
        sa.Column('description', sa.String(), nullable=True),
        sa.Column('is_active', sa.Boolean(), server_default=sa.text('true'), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
        sa.UniqueConstraint('name', name='uq_risk_groups_name'),
    )


def downgrade() -> None:
    op.drop_table('risk_groups')
    op.drop_column('trading_profiles', 'risk_group')
