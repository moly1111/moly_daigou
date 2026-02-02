"""规格改为直接存 price/cost，移除 extra_price

Revision ID: variant_direct_price
Revises: add_variant_local_id
Create Date: 2026-01-30

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import text


revision = 'variant_direct_price'
down_revision = 'add_variant_local_id'
branch_labels = None
depends_on = None


def upgrade():
    conn = op.get_bind()
    insp = sa.inspect(conn)
    cols = [c['name'] for c in insp.get_columns('product_variant')]

    # 1) 添加 price、cost 列
    if 'price' not in cols:
        with op.batch_alter_table('product_variant', schema=None) as batch_op:
            batch_op.add_column(sa.Column('price', sa.Numeric(10, 2), nullable=True))
            batch_op.add_column(sa.Column('cost', sa.Numeric(10, 2), nullable=True))

    # 2) 回填：price = product.price_rmb + variant.extra_price；cost = product.cost_price_rmb（历史无按规格成本）
    result = conn.execute(text('''
        SELECT pv.id, pv.product_id, pv.extra_price, p.price_rmb, p.cost_price_rmb
        FROM product_variant pv
        JOIN product p ON pv.product_id = p.id
    '''))
    for row in result:
        vid, pid, extra, base_price, base_cost = row
        price_val = float(base_price or 0) + float(extra or 0)
        cost_val = float(base_cost or 0)
        conn.execute(
            text('UPDATE product_variant SET price = :p, cost = :c WHERE id = :vid'),
            {'p': price_val, 'c': cost_val, 'vid': vid}
        )

    # 3) 删除 extra_price
    with op.batch_alter_table('product_variant', schema=None) as batch_op:
        batch_op.drop_column('extra_price')

    # 4) 更新 product 的 price_rmb、cost_price_rmb 为各规格 min（保持兼容）
    result = conn.execute(text('''
        SELECT product_id, MIN(price) as min_price, MIN(cost) as min_cost
        FROM product_variant
        GROUP BY product_id
    '''))
    for row in result:
        pid, min_p, min_c = row
        conn.execute(
            text('UPDATE product SET price_rmb = :p, cost_price_rmb = :c WHERE id = :pid'),
            {'p': float(min_p or 0), 'c': float(min_c or 0), 'pid': pid}
        )


def downgrade():
    # 恢复 extra_price，从 price - product.price_rmb 计算
    with op.batch_alter_table('product_variant', schema=None) as batch_op:
        batch_op.add_column(sa.Column('extra_price', sa.Numeric(10, 2), nullable=True, server_default='0'))
    conn = op.get_bind()
    result = conn.execute(text('''
        SELECT pv.id, pv.price, p.price_rmb
        FROM product_variant pv
        JOIN product p ON pv.product_id = p.id
    '''))
    for row in result:
        vid, price_val, base = row
        extra = float(price_val or 0) - float(base or 0)
        conn.execute(text('UPDATE product_variant SET extra_price = :e WHERE id = :vid'), {'e': extra, 'vid': vid})
    with op.batch_alter_table('product_variant', schema=None) as batch_op:
        batch_op.drop_column('price')
        batch_op.drop_column('cost')
