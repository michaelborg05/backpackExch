"""add_profile_trading_hours

Revision ID: e7f8a9b0c1d2
Revises: c2f7f4e162cf
Create Date: 2026-05-16 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e7f8a9b0c1d2'
down_revision: Union[str, Sequence[str], None] = 'c2f7f4e162cf'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Mon–Fri: two sessions per day (UTC). Sat/Sun: no windows = closed.
_DEFAULT_WINDOWS = [
    (0, '03:00', '12:00'),
    (0, '14:00', '21:00'),
    (1, '03:00', '12:00'),
    (1, '14:00', '21:00'),
    (2, '03:00', '12:00'),
    (2, '14:00', '21:00'),
    (3, '03:00', '12:00'),
    (3, '14:00', '21:00'),
    (4, '03:00', '12:00'),
    (4, '14:00', '21:00'),
]


def upgrade() -> None:
    op.create_table(
        'profile_trading_hours',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('profile_name', sa.String(), nullable=False),
        sa.Column('day_of_week', sa.Integer(), nullable=False),  # 0=Mon … 6=Sun
        sa.Column('start_time', sa.String(5), nullable=False),   # "HH:MM" UTC
        sa.Column('end_time', sa.String(5), nullable=False),     # "HH:MM" UTC
        sa.Column('enabled', sa.Boolean(), nullable=False, server_default=sa.text('true')),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index(
        'ix_profile_trading_hours_profile',
        'profile_trading_hours',
        ['profile_name'],
    )

    # Seed default windows for every existing profile
    conn = op.get_bind()
    profiles = conn.execute(sa.text("SELECT name FROM trading_profiles")).fetchall()
    if profiles:
        rows = [
            {"profile_name": row[0], "day_of_week": day, "start_time": start, "end_time": end}
            for row in profiles
            for day, start, end in _DEFAULT_WINDOWS
        ]
        conn.execute(
            sa.text(
                "INSERT INTO profile_trading_hours (profile_name, day_of_week, start_time, end_time, enabled) "
                "VALUES (:profile_name, :day_of_week, :start_time, :end_time, true)"
            ),
            rows,
        )


def downgrade() -> None:
    op.drop_index('ix_profile_trading_hours_profile', table_name='profile_trading_hours')
    op.drop_table('profile_trading_hours')
