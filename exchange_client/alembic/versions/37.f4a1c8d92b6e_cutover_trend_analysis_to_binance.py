"""cutover trend_analysis_log to the Binance candle fetcher

Archives the pre-cutover TradingView-sourced trend_analysis_log as
trend_analysis_log_tv_archive (data kept, not dropped), then promotes
trend_analysis_shadow (the Binance-sourced candle fetcher table, running in
parallel for the past year) to be the new trend_analysis_log.

Revision ID: f4a1c8d92b6e
Revises: 192ec64e0046
Create Date: 2026-07-25 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f4a1c8d92b6e'
down_revision: Union[str, Sequence[str], None] = '192ec64e0046'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # 1. Archive the old TradingView-sourced live table — renamed, not dropped.
    op.execute("ALTER TABLE trend_analysis_log RENAME CONSTRAINT trend_analysis_log_pkey TO trend_analysis_log_tv_archive_pkey")
    op.execute("ALTER INDEX ix_trend_log_lookup RENAME TO ix_trend_log_tv_archive_lookup")
    op.execute("ALTER INDEX ix_trend_analysis_log_symbol RENAME TO ix_trend_analysis_log_tv_archive_symbol")
    op.execute("ALTER INDEX ix_trend_analysis_log_timeframe RENAME TO ix_trend_analysis_log_tv_archive_timeframe")
    op.execute("ALTER INDEX ix_trend_analysis_log_timestamp RENAME TO ix_trend_analysis_log_tv_archive_timestamp")
    op.rename_table('trend_analysis_log', 'trend_analysis_log_tv_archive')

    # 2. Promote the Binance shadow table to be the new trend_analysis_log.
    op.execute("ALTER TABLE trend_analysis_shadow RENAME CONSTRAINT trend_analysis_shadow_pkey TO trend_analysis_log_pkey")
    op.execute("ALTER TABLE trend_analysis_shadow RENAME CONSTRAINT uq_trend_shadow_bar TO uq_trend_log_bar")
    op.execute("ALTER INDEX ix_trend_shadow_lookup RENAME TO ix_trend_log_lookup")
    op.execute("ALTER INDEX ix_trend_analysis_shadow_symbol RENAME TO ix_trend_analysis_log_symbol")
    op.execute("ALTER INDEX ix_trend_analysis_shadow_timeframe RENAME TO ix_trend_analysis_log_timeframe")
    op.execute("ALTER INDEX ix_trend_analysis_shadow_timestamp RENAME TO ix_trend_analysis_log_timestamp")
    op.execute("ALTER INDEX ix_trend_analysis_shadow_source RENAME TO ix_trend_analysis_log_source")
    op.rename_table('trend_analysis_shadow', 'trend_analysis_log')


def downgrade() -> None:
    """Reverse the cutover: demote the new trend_analysis_log back to trend_analysis_shadow,
    then restore trend_analysis_log_tv_archive as trend_analysis_log."""
    # 2 reversed.
    op.rename_table('trend_analysis_log', 'trend_analysis_shadow')
    op.execute("ALTER INDEX ix_trend_analysis_log_source RENAME TO ix_trend_analysis_shadow_source")
    op.execute("ALTER INDEX ix_trend_analysis_log_timestamp RENAME TO ix_trend_analysis_shadow_timestamp")
    op.execute("ALTER INDEX ix_trend_analysis_log_timeframe RENAME TO ix_trend_analysis_shadow_timeframe")
    op.execute("ALTER INDEX ix_trend_analysis_log_symbol RENAME TO ix_trend_analysis_shadow_symbol")
    op.execute("ALTER INDEX ix_trend_log_lookup RENAME TO ix_trend_shadow_lookup")
    op.execute("ALTER TABLE trend_analysis_shadow RENAME CONSTRAINT uq_trend_log_bar TO uq_trend_shadow_bar")
    op.execute("ALTER TABLE trend_analysis_shadow RENAME CONSTRAINT trend_analysis_log_pkey TO trend_analysis_shadow_pkey")

    # 1 reversed.
    op.rename_table('trend_analysis_log_tv_archive', 'trend_analysis_log')
    op.execute("ALTER INDEX ix_trend_analysis_log_tv_archive_timestamp RENAME TO ix_trend_analysis_log_timestamp")
    op.execute("ALTER INDEX ix_trend_analysis_log_tv_archive_timeframe RENAME TO ix_trend_analysis_log_timeframe")
    op.execute("ALTER INDEX ix_trend_analysis_log_tv_archive_symbol RENAME TO ix_trend_analysis_log_symbol")
    op.execute("ALTER INDEX ix_trend_log_tv_archive_lookup RENAME TO ix_trend_log_lookup")
    op.execute("ALTER TABLE trend_analysis_log_tv_archive RENAME CONSTRAINT trend_analysis_log_tv_archive_pkey TO trend_analysis_log_pkey")
