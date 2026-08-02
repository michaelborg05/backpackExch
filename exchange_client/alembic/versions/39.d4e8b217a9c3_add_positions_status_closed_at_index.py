"""add index on positions (status, closed_at)

Speeds up the daily realized P&L query used by the dashboard
(/profiles/daily-pnl and /dashboard/summary), which filters on
status = 'CLOSED' AND closed_at >= <day start>. The existing indexes
lead with profile_name + symbol, so this scan previously fell back to
reading all of a profile's rows.

Revision ID: d4e8b217a9c3
Revises: 865ac7d2b5c5
Create Date: 2026-08-01 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd4e8b217a9c3'
down_revision: Union[str, Sequence[str], None] = '865ac7d2b5c5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_index(
        'ix_positions_status_closed_at',
        'positions',
        ['status', 'closed_at'],
    )


def downgrade() -> None:
    op.drop_index('ix_positions_status_closed_at', table_name='positions')
