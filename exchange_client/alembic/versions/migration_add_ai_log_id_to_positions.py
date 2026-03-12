"""add ai_log_id to positions

Revision ID: c4d5e6f7a8b9
Revises: b3c4d5e6f7a8
Create Date: 2026-03-12

Adds:
  - positions.ai_log_id : FK to ai_signal_log.id so we can resolve
    AI signal outcomes when the position closes.
    Nullable — only set for positions opened from AI_AGENT profiles.
"""
from alembic import op
import sqlalchemy as sa

revision      = 'c4d5e6f7a8b9'
down_revision = 'b3c4d5e6f7a8'   # the AI tables migration
branch_labels = None
depends_on    = None


def upgrade():
    op.add_column(
        'positions',
        sa.Column(
            'ai_log_id',
            sa.Integer(),
            sa.ForeignKey('ai_signal_log.id', ondelete='SET NULL'),
            nullable=True,
            comment='FK to ai_signal_log — set for AI_AGENT profile positions only',
        )
    )
    op.create_index(
        'ix_positions_ai_log_id',
        'positions',
        ['ai_log_id'],
        unique=False,
    )


def downgrade():
    op.drop_index('ix_positions_ai_log_id', table_name='positions')
    op.drop_column('positions', 'ai_log_id')
