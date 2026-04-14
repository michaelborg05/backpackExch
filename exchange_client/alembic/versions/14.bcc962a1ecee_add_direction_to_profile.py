"""add_direction_to_profile

Revision ID: bcc962a1ecee
Revises: 76d11a90f3ac
Create Date: 2026-04-14 20:31:28.130772

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'bcc962a1ecee'
down_revision: Union[str, Sequence[str], None] = '76d11a90f3ac'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── trading_profiles: add direction ───────────────
    op.add_column(
        'trading_profiles',
        sa.Column('direction', sa.String(), nullable=True, server_default='LONG')
    )
    op.create_check_constraint(
        'valid_profile_direction',
        'trading_profiles',
        "direction IN ('LONG', 'SHORT') OR direction IS NULL"
    )
    op.drop_column('trading_profiles', 'api_key')
    op.drop_column('trading_profiles', 'secret')

def downgrade() -> None:
    op.drop_column('trading_profiles', 'direction')
    op.add_column('trading_profiles', sa.Column('api_key', sa.String(), nullable=True))
    op.add_column('trading_profiles', sa.Column('secret', sa.String(), nullable=True))

