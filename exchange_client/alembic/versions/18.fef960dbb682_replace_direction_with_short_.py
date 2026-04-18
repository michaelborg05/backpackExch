"""17.replace_direction_with_short_strategy_types

Migrate profiles that have direction='SHORT' to use the new short strategy
type values (short_trend_following, short_mean_reversion), then drop the
direction column from trading_profiles.

Revision ID: fef960dbb682
Revises: fcf4221471e1
Create Date: 2026-04-18 22:52:21.759246

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'fef960dbb682'
down_revision: Union[str, Sequence[str], None] = 'fcf4221471e1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Migrate existing SHORT profiles: map direction='SHORT' + strategy_type
    # to the new combined strategy type values.
    op.execute("""
        UPDATE trading_profiles
        SET strategy_type = 'short_trend_following'
        WHERE direction = 'SHORT'
          AND (strategy_type = 'trend_following' OR strategy_type IS NULL)
    """)
    op.execute("""
        UPDATE trading_profiles
        SET strategy_type = 'short_mean_reversion'
        WHERE direction = 'SHORT'
          AND strategy_type = 'mean_reversion'
    """)
    # Drop the now-redundant direction column
    op.drop_column('trading_profiles', 'direction')


def downgrade() -> None:
    # Re-add direction column with LONG as default
    op.add_column(
        'trading_profiles',
        sa.Column('direction', sa.String(), server_default=sa.text("'LONG'"), nullable=True)
    )
    # Restore direction='SHORT' for profiles that were migrated
    op.execute("""
        UPDATE trading_profiles
        SET direction = 'SHORT',
            strategy_type = 'trend_following'
        WHERE strategy_type = 'short_trend_following'
    """)
    op.execute("""
        UPDATE trading_profiles
        SET direction = 'SHORT',
            strategy_type = 'mean_reversion'
        WHERE strategy_type = 'short_mean_reversion'
    """)
