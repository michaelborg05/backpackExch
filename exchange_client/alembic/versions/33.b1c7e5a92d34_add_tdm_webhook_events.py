"""add tdm_webhook_events table

Revision ID: b1c7e5a92d34
Revises: a8d4e7c92f10
Create Date: 2026-07-15 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


# revision identifiers, used by Alembic.
revision: str = 'b1c7e5a92d34'
down_revision: Union[str, Sequence[str], None] = 'a8d4e7c92f10'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'tdm_webhook_events',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('received_at', sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text('now()')),
        sa.Column('remote_addr', sa.String(), nullable=True),
        sa.Column('method', sa.String(), nullable=True),
        sa.Column('path', sa.String(), nullable=True),
        sa.Column('topic_id', sa.String(), nullable=True),
        sa.Column('headers', JSONB(), nullable=True),
        sa.Column('query_params', JSONB(), nullable=True),
        sa.Column('body', JSONB(), nullable=True),
        sa.Column('body_text', sa.Text(), nullable=True),
    )
    op.create_index('ix_tdm_webhook_events_received_at', 'tdm_webhook_events',
                    ['received_at'])
    op.create_index('ix_tdm_webhook_events_topic_id', 'tdm_webhook_events',
                    ['topic_id'])


def downgrade() -> None:
    op.drop_index('ix_tdm_webhook_events_topic_id', table_name='tdm_webhook_events')
    op.drop_index('ix_tdm_webhook_events_received_at', table_name='tdm_webhook_events')
    op.drop_table('tdm_webhook_events')
