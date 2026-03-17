"""migration_add_prompts_and_audit

Revision ID: 19bb90f164bf
Revises: c4d5e6f7a8b9
Create Date: 2026-03-17 17:35:41.795997

Adds:
  - ai_prompts        : versioned, DB-backed system prompts for the AI agent
  - config_audit_log  : generic append-only audit trail for config changes
                        (indicators, ai_prompts, profile settings, etc.)

Seeds ai_prompts with the current hardcoded system prompt so no data is lost
on first deploy.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

# revision identifiers, used by Alembic.
revision: str = '19bb90f164bf'
down_revision = 'c4d5e6f7a8b9'
branch_labels = None
depends_on = None


def upgrade():

    # ── ai_prompts ────────────────────────────────────────────────────────────
    op.create_table(
        'ai_prompts',

        sa.Column('id',            sa.Integer(),     primary_key=True),
        sa.Column('name',          sa.String(128),   nullable=False),
        sa.Column('strategy_type', sa.String(64),    nullable=True),   # trend_following | mean_reversion | range | swing | None=global
        sa.Column('profile_id',    sa.Integer(),     sa.ForeignKey('trading_profiles.id', ondelete='SET NULL'), nullable=True),
        sa.Column('system_prompt', sa.Text(),         nullable=False),
        sa.Column('is_active',     sa.Boolean(),     nullable=False, server_default='true'),
        sa.Column('is_default',    sa.Boolean(),     nullable=False, server_default='false'),
        sa.Column('version',       sa.Integer(),     nullable=False, server_default='1'),
        sa.Column('notes',         sa.Text(),         nullable=True),
        sa.Column('created_at',    sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('updated_at',    sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    op.create_index('ix_ai_prompts_strategy_type', 'ai_prompts', ['strategy_type'])
    op.create_index('ix_ai_prompts_profile_id',    'ai_prompts', ['profile_id'])
    op.create_index('ix_ai_prompts_is_default',    'ai_prompts', ['is_default'])

    # ── config_audit_log ──────────────────────────────────────────────────────
    op.create_table(
        'config_audit_log',

        sa.Column('id',          sa.Integer(),  primary_key=True),
        sa.Column('changed_at',  sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),

        # What kind of thing changed
        sa.Column('type',        sa.String(32),  nullable=False),   # indicator | ai_prompt | profile | symbol_config
        sa.Column('subtype',     sa.String(64),  nullable=True),    # trend | entry | exit | mean_reversion | system …

        # What happened
        sa.Column('action',      sa.String(16),  nullable=False),   # create | update | delete | set_default | toggle

        # Linkback to the affected row (NULL if the row was deleted)
        sa.Column('entity_id',   sa.Integer(),   nullable=True),
        sa.Column('entity_name', sa.String(256), nullable=True),    # human-readable label for UI

        # Who/what triggered the change
        sa.Column('changed_by',  sa.String(64),  nullable=False, server_default='web_ui'),

        # Full before/after snapshots stored as JSONB
        sa.Column('before',      JSONB,          nullable=True),
        sa.Column('after',       JSONB,          nullable=True),
    )

    op.create_index('ix_audit_changed_at',   'config_audit_log', ['changed_at'])
    op.create_index('ix_audit_type_subtype', 'config_audit_log', ['type', 'subtype'])
    op.create_index('ix_audit_entity',       'config_audit_log', ['entity_id', 'type'])

    # ── Seed: migrate the hardcoded system prompt into the new table ──────────
    op.execute("""
        INSERT INTO ai_prompts (
            name, strategy_type, profile_id,
            system_prompt, is_active, is_default, version, notes
        ) VALUES (
            'Default – All Strategies',
            NULL,
            NULL,
            'You are an expert crypto trader specialising in multi-timeframe
trend-following and mean-reversion entries on 15-minute candles. You are embedded
in an algorithmic trading system. The 60-minute trend gates have ALREADY passed.
Your job is purely 15m entry timing discretion.

Your strengths:
- Reading candle quality (body size, wick positioning, volume confirmation)
- Identifying optimal RSI entry windows (trajectory, not just threshold)
- Spotting technically-valid-but-contextually-weak setups (low volume, late entry)
- Suggesting asymmetric risk/reward levels based on recent structure

Rules:
- Be decisive. WAIT is valid but use sparingly — only when one more candle would
  meaningfully change your view.
- SKIP means the setup is genuinely poor, not just uncertain.
- Position size 1-5% of portfolio. Scale with confidence:
  <0.60 → 1%, 0.60-0.75 → 2%, 0.75-0.85 → 3%, >0.85 → 4-5%
- Stop loss: below recent structure low for longs.
- Take profit: minimum 1.5:1 RR, prefer 2:1+.
- Volume is a soft signal only. Crypto volume varies significantly by time of day
  and day of week (Asian/US/EU session gaps, weekend illiquidity). Never hard-block
  an entry on low volume alone — use it only to shade confidence down by 0.05-0.10
  max. A good setup with low volume is still a good setup.
- The trading system''s minimum confidence threshold is 72%% (0.72).
  If you assess confidence >= 0.72, you MUST return ENTER.
  WAIT is only valid for confidence 0.55-0.71.
  Below 0.55, return SKIP.
  Respond ONLY with valid JSON. No markdown. No preamble.',
            true,
            true,
            1,
            'Seeded from hardcoded _system_prompt on migration. Global default — applies to all profiles/strategies unless overridden.'
        )
    """)


def downgrade():
    op.drop_table('config_audit_log')
    op.drop_table('ai_prompts')
