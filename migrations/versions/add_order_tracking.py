"""add order tracking_number and shipped_at

Revision ID: add_order_tracking
Revises: add_product_variant
Create Date: 2026-01-30

"""
from alembic import op
import sqlalchemy as sa


revision = 'add_order_tracking'
down_revision = 'add_product_variant'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('order', schema=None) as batch_op:
        batch_op.add_column(sa.Column('tracking_number', sa.String(100), nullable=True))
        batch_op.add_column(sa.Column('shipped_at', sa.DateTime(), nullable=True))


def downgrade():
    with op.batch_alter_table('order', schema=None) as batch_op:
        batch_op.drop_column('shipped_at')
        batch_op.drop_column('tracking_number')
