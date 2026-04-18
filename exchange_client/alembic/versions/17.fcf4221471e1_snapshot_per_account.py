"""snapshot_per_account

Revision ID: fcf4221471e1
Revises: b2e1285a91e8
Create Date: 2026-04-18 22:51:57.132092

Redesigns daily_balance_snapshots to be keyed purely by exchange account.
One row per account per UTC day. profile_name is dropped as a key.

Steps:
1. Backfill account_id from trading_profiles for any snapshot rows where it is NULL
2. Delete any remaining rows still NULL (orphaned / no linked profile)
3. Deduplicate: for each (account_id, utc-date) keep the snapshot with the lowest id
4. Add partial unique index on (account_id, date)
5. Make account_id NOT NULL
6. Make profile_name nullable (kept only as informational label, no longer a key)
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'fcf4221471e1'
down_revision: Union[str, Sequence[str], None] = 'b2e1285a91e8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Backfill account_id from trading_profiles where it is missing
    op.execute("""
        UPDATE daily_balance_snapshots s
        SET account_id = p.account_id
        FROM trading_profiles p
        WHERE s.profile_name = p.name
          AND s.account_id IS NULL
          AND p.account_id IS NOT NULL
    """)

    # 2. Delete any rows that still have no account_id (orphaned snapshots)
    op.execute("""
        DELETE FROM daily_balance_snapshots
        WHERE account_id IS NULL
    """)

    # 3. Deduplicate: per (account_id, utc-date) keep lowest id, delete siblings
    op.execute("""
        DELETE FROM daily_balance_snapshots
        WHERE id NOT IN (
            SELECT MIN(id)
            FROM daily_balance_snapshots
            GROUP BY account_id, DATE(snapshot_date AT TIME ZONE 'UTC')
        )
    """)

    # 4. Partial unique index — one row per account per day
    op.execute("""
        CREATE UNIQUE INDEX uq_snapshot_account_date
        ON daily_balance_snapshots (account_id, DATE(snapshot_date AT TIME ZONE 'UTC'))
    """)

    # 5. Make account_id NOT NULL now that all rows have a value
    op.alter_column(
        'daily_balance_snapshots', 'account_id',
        existing_type=sa.Integer(),
        nullable=False,
    )

    # 6. Make profile_name nullable — it is no longer the primary key
    op.alter_column(
        'daily_balance_snapshots', 'profile_name',
        existing_type=sa.String(),
        nullable=True,
    )


def downgrade() -> None:
    op.alter_column(
        'daily_balance_snapshots', 'account_id',
        existing_type=sa.Integer(),
        nullable=True,
    )
    op.alter_column(
        'daily_balance_snapshots', 'profile_name',
        existing_type=sa.String(),
        nullable=False,
    )
    op.execute("DROP INDEX IF EXISTS uq_snapshot_account_date")
