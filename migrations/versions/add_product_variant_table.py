"""add product_variant table and migrate variants from JSON

Revision ID: add_product_variant
Revises: 7bc92180036c
Create Date: 2026-01-30

"""
from alembic import op
import sqlalchemy as sa


revision = 'add_product_variant'
down_revision = '7bc92180036c'
branch_labels = None
depends_on = None


def upgrade():
    import json
    from sqlalchemy import text
    from sqlalchemy.engine import reflection
    connection = op.get_bind()
    insp = reflection.Inspector.from_engine(connection)

    # 1) 创建规格表（若不存在）
    if 'product_variant' not in insp.get_table_names():
        op.create_table(
            'product_variant',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('product_id', sa.Integer(), nullable=False),
            sa.Column('name', sa.String(100), nullable=False),
            sa.Column('extra_price', sa.Numeric(10, 2), nullable=True, server_default='0'),
            sa.Column('image', sa.String(512), nullable=True),
            sa.Column('sort_order', sa.Integer(), nullable=True, server_default='0'),
            sa.Column('stock', sa.Integer(), nullable=True, server_default='0'),
            sa.ForeignKeyConstraint(['product_id'], ['product.id'], ondelete='CASCADE'),
            sa.PrimaryKeyConstraint('id'),
        )
        op.create_index('ix_product_variant_product_id', 'product_variant', ['product_id'], unique=False)

    # 2) 为 order_item、cart_item 添加 variant_id（若不存在）
    oi_cols = [c['name'] for c in insp.get_columns('order_item')]
    if 'variant_id' not in oi_cols:
        with op.batch_alter_table('order_item', schema=None) as batch_op:
            batch_op.add_column(sa.Column('variant_id', sa.Integer(), nullable=True))
            batch_op.create_foreign_key('fk_order_item_variant_id', 'product_variant', ['variant_id'], ['id'])
    ci_cols = [c['name'] for c in insp.get_columns('cart_item')]
    if 'variant_id' not in ci_cols:
        with op.batch_alter_table('cart_item', schema=None) as batch_op:
            batch_op.add_column(sa.Column('variant_id', sa.Integer(), nullable=True))
            batch_op.create_foreign_key('fk_cart_item_variant_id', 'product_variant', ['variant_id'], ['id'])

    # 3) 数据迁移：Product.variants JSON -> ProductVariant 行，并回填 variant_id
    product_cols = [c['name'] for c in insp.get_columns('product')]
    if 'variants' in product_cols:
        rp = connection.execute(text('SELECT id, variants FROM product WHERE variants IS NOT NULL AND variants != ""'))
        for (pid, variants_text) in rp.fetchall():
            try:
                vlist = json.loads(variants_text) if isinstance(variants_text, str) else []
            except Exception:
                vlist = []
            for idx, v in enumerate(vlist):
                name = (v.get('name') or '').strip()[:100]
                extra = float(v.get('extra_price') or 0)
                img = (v.get('image') or '')[:512] if v.get('image') else None
                connection.execute(
                    text(
                        'INSERT INTO product_variant (product_id, name, extra_price, image, sort_order, stock) '
                        'VALUES (:pid, :name, :extra, :img, :idx, 0)'
                    ),
                    {'pid': pid, 'name': name, 'extra': extra, 'img': img, 'idx': idx},
                )
    ro = connection.execute(text(
        'SELECT oi.id, oi.product_id, oi.variant_name FROM order_item oi '
        'WHERE oi.variant_name IS NOT NULL AND oi.variant_name != "" AND oi.product_id IS NOT NULL'
    ))
    for (oi_id, product_id, variant_name) in ro.fetchall():
        rv = connection.execute(
            text('SELECT id FROM product_variant WHERE product_id = :pid AND name = :name LIMIT 1'),
            {'pid': product_id, 'name': (variant_name or '').strip()},
        )
        row = rv.fetchone()
        if row:
            connection.execute(text('UPDATE order_item SET variant_id = :vid WHERE id = :oid'), {'vid': row[0], 'oid': oi_id})
    rc = connection.execute(text(
        'SELECT ci.id, ci.product_id, ci.variant_name FROM cart_item ci '
        'WHERE ci.variant_name IS NOT NULL AND ci.variant_name != ""'
    ))
    for (ci_id, product_id, variant_name) in rc.fetchall():
        rv = connection.execute(
            text('SELECT id FROM product_variant WHERE product_id = :pid AND name = :name LIMIT 1'),
            {'pid': product_id, 'name': (variant_name or '').strip()},
        )
        row = rv.fetchone()
        if row:
            connection.execute(text('UPDATE cart_item SET variant_id = :vid WHERE id = :cid'), {'vid': row[0], 'cid': ci_id})

    # 4) 删除 product.variants 列（若存在）
    if 'variants' in product_cols:
        with op.batch_alter_table('product', schema=None) as batch_op:
            batch_op.drop_column('variants')


def downgrade():
    with op.batch_alter_table('product', schema=None) as batch_op:
        batch_op.add_column(sa.Column('variants', sa.Text(), nullable=True))
    with op.batch_alter_table('order_item', schema=None) as batch_op:
        batch_op.drop_constraint('fk_order_item_variant_id', type_='foreignkey')
        batch_op.drop_column('variant_id')
    with op.batch_alter_table('cart_item', schema=None) as batch_op:
        batch_op.drop_constraint('fk_cart_item_variant_id', type_='foreignkey')
        batch_op.drop_column('variant_id')
    op.drop_index('ix_product_variant_product_id', table_name='product_variant')
    op.drop_table('product_variant')
