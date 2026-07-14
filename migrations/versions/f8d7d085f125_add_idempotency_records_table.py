"""add idempotency_records table

Revision ID: f8d7d085f125
Revises: 001_initial_b2b_schema
Create Date: 2026-07-14
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'f8d7d085f125'
down_revision = '001_initial_b2b_schema'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'idempotency_records',
        sa.Column('id', sa.Integer(), primary_key=True, index=True),
        sa.Column('key', sa.String(255), unique=True, nullable=False, index=True),
        sa.Column('product_id', sa.Integer(), sa.ForeignKey('products.id', ondelete='CASCADE'), nullable=False),
        sa.Column('event_type', sa.String(50), nullable=False),
        sa.Column('processed_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table('idempotency_records')