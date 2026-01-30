"""add product_variant.local_id (逻辑规格编号，按商品从 1 开始)

Revision ID: add_variant_local_id
Revises: add_order_tracking
Create Date: 2026-01-30

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import text


revision = 'add_variant_local_id'
down_revision = 'add_order_tracking'
branch_labels = None
depends_on = None


def upgrade():
    # 1) 添加 local_id 列（先可空，回填后再加唯一约束）
    conn = op.get_bind()
    insp = sa.inspect(conn)
    cols = [c['name'] for c in insp.get_columns('product_variant')]
    if 'local_id' not in cols:
        with op.batch_alter_table('product_variant', schema=None) as batch_op:
            batch_op.add_column(sa.Column('local_id', sa.Integer(), nullable=True))

    # 2) 回填：每个 product_id 下按 id 排序，依次赋 1, 2, 3...
    result = conn.execute(
        text('SELECT id, product_id FROM product_variant ORDER BY product_id, id')
    )
    rows = result.fetchall()
    by_product = {}
    for row in rows:
        pid = row[1]
        by_product.setdefault(pid, []).append(row[0])
    for pid, ids in by_product.items():
        for i, vid in enumerate(ids, start=1):
            conn.execute(
                text('UPDATE product_variant SET local_id = :lid WHERE id = :vid'),
                {'lid': i, 'vid': vid}
            )

    # 3) 创建唯一约束（SQLite 不便于把列改为 NOT NULL，保留可空；应用层新建时必填 local_id）
    with op.batch_alter_table('product_variant', schema=None) as batch_op:
        batch_op.create_unique_constraint(
            'uq_product_variant_product_local',
            ['product_id', 'local_id'],
        )


def downgrade():
    with op.batch_alter_table('product_variant', schema=None) as batch_op:
        batch_op.drop_constraint('uq_product_variant_product_local', type_='unique')
        batch_op.drop_column('local_id')
