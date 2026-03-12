"""add ai signal log and stats tables

Revision ID: b3c4d5e6f7a8
Revises: <your_last_revision_id>
Create Date: 2026-03-12

Adds:
  - ai_signal_log      : per-signal AI vs rules comparison log
  - ai_vs_rules_stats  : materialised weekly performance comparison

Also adds strategy_type value 'ai_agent' to TradingProfileDB (no schema
change needed — it's a String column with no constraint on values).
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision    = 'b3c4d5e6f7a8'
down_revision = '06ca3eee9323'   # ← replace with your last revision id
branch_labels = None
depends_on    = None


def upgrade():

    # ── ai_signal_log ─────────────────────────────────────────────────────────
    op.create_table(
        'ai_signal_log',

        sa.Column('id',           sa.Integer(),  primary_key=True),
        sa.Column('pair',         sa.String(20), nullable=False),
        sa.Column('profile_name', sa.String(50), nullable=False),
        sa.Column('signal_source',sa.String(10), nullable=False, server_default='SHADOW'),
        sa.Column('candle_time',  sa.DateTime(timezone=True), nullable=False),
        sa.Column('timeframe',    sa.String(5),  nullable=False),
        sa.Column('timestamp',    sa.DateTime(timezone=True),
                  server_default=sa.func.now()),

        # 60m gate
        sa.Column('gate_60m_passed', sa.Boolean(), nullable=False),
        sa.Column('gate_60m_data',   JSONB),

        # AI decision
        sa.Column('ai_decision',          sa.String(10)),
        sa.Column('ai_confidence',        sa.Numeric(4, 3)),
        sa.Column('ai_reasoning',         sa.Text()),
        sa.Column('ai_risk_flags',        JSONB),
        sa.Column('ai_entry_price',       sa.Numeric(20, 8)),
        sa.Column('ai_stop_loss',         sa.Numeric(20, 8)),
        sa.Column('ai_take_profit',       sa.Numeric(20, 8)),
        sa.Column('ai_position_size_pct', sa.Numeric(5, 2)),

        # Rules decision (parallel, for comparison)
        sa.Column('rules_decision',    sa.String(10)),
        sa.Column('rules_entry_price', sa.Numeric(20, 8)),

        # Outcome (filled in later by OutcomeResolver)
        sa.Column('outcome_resolved',     sa.Boolean(), nullable=False,
                  server_default=sa.text('false')),
        sa.Column('outcome_result',       sa.String(10)),
        sa.Column('outcome_pnl_pct',      sa.Numeric(8, 4)),
        sa.Column('outcome_exit_price',   sa.Numeric(20, 8)),
        sa.Column('outcome_exit_time',    sa.DateTime(timezone=True)),
        sa.Column('outcome_candles_held', sa.Integer()),

        # Raw snapshot for replay
        sa.Column('context_snapshot', JSONB),

        # Constraints
        sa.CheckConstraint(
            "ai_decision IN ('ENTER', 'SKIP', 'WAIT')",
            name='valid_ai_decision'
        ),
        sa.CheckConstraint(
            "rules_decision IN ('ENTER', 'SKIP')",
            name='valid_rules_decision'
        ),
        sa.CheckConstraint(
            "outcome_result IN ('WIN', 'LOSS', 'BREAKEVEN', 'MISSED') "
            "OR outcome_result IS NULL",
            name='valid_outcome_result'
        ),
    )

    op.create_index('ix_ai_signal_log_pair_time',   'ai_signal_log', ['pair', 'timestamp'])
    op.create_index('ix_ai_signal_log_profile',     'ai_signal_log', ['profile_name'])
    op.create_index('ix_ai_signal_log_unresolved',  'ai_signal_log',
                    ['outcome_resolved', 'ai_decision'])

    # ── ai_vs_rules_stats ─────────────────────────────────────────────────────
    op.create_table(
        'ai_vs_rules_stats',

        sa.Column('id',           sa.Integer(),  primary_key=True),
        sa.Column('computed_at',  sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('period_start', sa.DateTime(timezone=True), nullable=False),
        sa.Column('period_end',   sa.DateTime(timezone=True), nullable=False),
        sa.Column('pair',         sa.String(20), nullable=False),
        sa.Column('profile_name', sa.String(50), nullable=False),

        # AI stats
        sa.Column('ai_total_signals',   sa.Integer()),
        sa.Column('ai_entries_taken',   sa.Integer()),
        sa.Column('ai_win_rate',        sa.Numeric(5, 2)),
        sa.Column('ai_avg_rr',          sa.Numeric(6, 3)),
        sa.Column('ai_avg_confidence',  sa.Numeric(4, 3)),
        sa.Column('ai_skipped_correct', sa.Integer()),
        sa.Column('ai_skipped_wrong',   sa.Integer()),

        # Rules stats
        sa.Column('rules_total_signals', sa.Integer()),
        sa.Column('rules_win_rate',      sa.Numeric(5, 2)),
        sa.Column('rules_avg_rr',        sa.Numeric(6, 3)),

        # Delta
        sa.Column('win_rate_delta', sa.Numeric(5, 2)),
        sa.Column('rr_delta',       sa.Numeric(6, 3)),
    )

    op.create_index('ix_ai_stats_pair_period',  'ai_vs_rules_stats', ['pair', 'period_start'])
    op.create_index('ix_ai_stats_computed_at',  'ai_vs_rules_stats', ['computed_at'])


def downgrade():
    op.drop_table('ai_vs_rules_stats')
    op.drop_table('ai_signal_log')
