"""update_default_trading_hours

Revision ID: a3b4c5d6e7f8
Revises: f1e2d3c4b5a6
Create Date: 2026-05-17 00:00:00.000000

Updates the seeded default trading-hour windows for Mon/Tue/Wed.
Only rows that still match the original default values are touched,
so any profile where hours were already customised is left unchanged.

Changes:
  Monday    session 1: start 03:00 → 05:00  (end 12:00 unchanged)
  Monday    session 2: start 14:00 → 15:00  (end 21:00 unchanged)
  Tuesday   session 1: start 03:00 → 02:00, end 12:00 → 23:00
  Tuesday   session 2: 14:00–21:00 removed
  Wednesday session 1: start 03:00 → 01:00  (end 12:00 unchanged)
  Wednesday session 2: end 21:00 → 23:00    (start 14:00 unchanged)

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'a3b4c5d6e7f8'
down_revision: Union[str, Sequence[str], None] = 'f1e2d3c4b5a6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(sa.text("""
        UPDATE profile_trading_hours
           SET start_time = '05:00'
         WHERE day_of_week = 0 AND start_time = '03:00' AND end_time = '12:00'
    """))

    op.execute(sa.text("""
        UPDATE profile_trading_hours
           SET start_time = '15:00'
         WHERE day_of_week = 0 AND start_time = '14:00' AND end_time = '21:00'
    """))

    op.execute(sa.text("""
        UPDATE profile_trading_hours
           SET start_time = '02:00', end_time = '23:00'
         WHERE day_of_week = 1 AND start_time = '03:00' AND end_time = '12:00'
    """))

    op.execute(sa.text("""
        DELETE FROM profile_trading_hours
         WHERE day_of_week = 1 AND start_time = '14:00' AND end_time = '21:00'
    """))

    op.execute(sa.text("""
        UPDATE profile_trading_hours
           SET start_time = '01:00'
         WHERE day_of_week = 2 AND start_time = '03:00' AND end_time = '12:00'
    """))

    op.execute(sa.text("""
        UPDATE profile_trading_hours
           SET end_time = '23:00'
         WHERE day_of_week = 2 AND start_time = '14:00' AND end_time = '21:00'
    """))


def downgrade() -> None:
    op.execute(sa.text("""
        UPDATE profile_trading_hours
           SET start_time = '03:00'
         WHERE day_of_week = 0 AND start_time = '05:00' AND end_time = '12:00'
    """))

    op.execute(sa.text("""
        UPDATE profile_trading_hours
           SET start_time = '14:00'
         WHERE day_of_week = 0 AND start_time = '15:00' AND end_time = '21:00'
    """))

    op.execute(sa.text("""
        UPDATE profile_trading_hours
           SET start_time = '03:00', end_time = '12:00'
         WHERE day_of_week = 1 AND start_time = '02:00' AND end_time = '23:00'
    """))

    # Re-insert Tuesday session 2 for all profiles that have a Tuesday session 1
    op.execute(sa.text("""
        INSERT INTO profile_trading_hours (profile_id, day_of_week, start_time, end_time, enabled)
        SELECT DISTINCT profile_id, 1, '14:00', '21:00', true
          FROM profile_trading_hours
         WHERE day_of_week = 1
    """))

    op.execute(sa.text("""
        UPDATE profile_trading_hours
           SET start_time = '03:00'
         WHERE day_of_week = 2 AND start_time = '01:00' AND end_time = '12:00'
    """))

    op.execute(sa.text("""
        UPDATE profile_trading_hours
           SET end_time = '21:00'
         WHERE day_of_week = 2 AND start_time = '14:00' AND end_time = '23:00'
    """))
