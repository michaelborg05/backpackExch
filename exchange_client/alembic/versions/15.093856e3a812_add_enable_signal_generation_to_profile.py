"""add_enable_signal_generation_to_profile

Revision ID: 093856e3a812
Revises: bcc962a1ecee
Create Date: 2026-04-15 12:19:17.672147

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '093856e3a812'
down_revision: Union[str, Sequence[str], None] = 'bcc962a1ecee'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'trading_profiles',
        sa.Column(
            'enable_signal_generation',
            sa.Boolean(),
            nullable=False,
            server_default=sa.text('true'),
        )
    )


def downgrade() -> None:
    op.drop_column('trading_profiles', 'enable_signal_generation')
