# 后台管理路由：登录、仪表盘、商品、用户、订单、设置、版本
import json
import logging
import os
import io
import csv
import random
import string
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify, current_app
from flask_login import login_required, login_user, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from sqlalchemy import func

from core.extensions import db
from core.models import (
    User, Address, Product, ProductVariant, Order, OrderItem, CartItem,
    AdminUser, SystemSettings, Version, ChatMessage,
    PaymentAttachment, EmailVerification,
)
from core.utils import get_setting, set_setting, allowed_file, generate_order_no, is_valid_email, admin_required, require_env, fill_order_items_unit_price, product_id_to_title_map, restore_order_stock
from services.send_email import send_email

admin_bp = Blueprint('admin', __name__)


# ---------- 登录 ----------
@admin_bp.route('/admin/login', methods=['GET', 'POST'])
def admin_login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        try:
            expected_username = require_env('ADMIN_USERNAME')
        except Exception:
            expected_username = None
        if not expected_username or username != expected_username:
            flash('用户名或密码错误', 'error')
            return render_template('admin/login.html')
        admin = AdminUser.query.filter_by(username=expected_username).first()
        if admin and check_password_hash(admin.password_hash, password):
            login_user(admin, remember=True, duration=__import__('datetime').timedelta(days=7))
            return redirect(url_for('admin.admin_dashboard'))
        flash('用户名或密码错误', 'error')
    return render_template('admin/login.html')


@admin_bp.route('/admin/logout')
@login_required
@admin_required
def admin_logout():
    logout_user()
    return redirect(url_for('admin.admin_login'))


# ---------- 数据库（只读查看） ----------
DATABASE_VIEW_MODELS = [
    ('用户', User),
    ('收货地址', Address),
    ('商品', Product),
    ('商品规格', ProductVariant),
    ('订单', Order),
    ('订单项', OrderItem),
    ('购物车项', CartItem),
    ('支付附件', PaymentAttachment),
    ('管理员', AdminUser),
    ('系统设置', SystemSettings),
    ('邮箱验证码', EmailVerification),
    ('版本', Version),
    ('聊天消息', ChatMessage),
]


def _row_to_readable_dict(model, row, mask_fields=None):
    """把一行 ORM 转成可读 dict，敏感字段用 *** 遮盖。"""
    if mask_fields is None:
        mask_fields = {'password_hash'}
    out = {}
    for col in model.__table__.columns:
        key = col.name
        val = getattr(row, key, None)
        if key in mask_fields and val:
            out[key] = '***'
        elif hasattr(val, 'isoformat'):
            out[key] = val.isoformat() if val else ''
        else:
            out[key] = val
    return out


@admin_bp.route('/admin/database')
@login_required
@admin_required
def admin_database():
    """数据库总览：列出所有表及行数。"""
    tables = []
    for label, model in DATABASE_VIEW_MODELS:
        try:
            count = model.query.count()
        except Exception:
            count = 0
        tables.append({
            'label': label,
            'tablename': model.__tablename__,
            'count': count,
        })
    return render_template('admin/database.html', tables=tables)


@admin_bp.route('/admin/database/<tablename>')
@login_required
@admin_required
def admin_database_table(tablename):
    """按表名查看数据（只读、分页）。"""
    model_by_name = {m.__tablename__: (label, m) for label, m in DATABASE_VIEW_MODELS}
    if tablename not in model_by_name:
        flash('表不存在', 'error')
        return redirect(url_for('admin.admin_database'))
    label, model = model_by_name[tablename]
    page = request.args.get('page', 1, type=int) or 1
    per_page = request.args.get('per_page', 50, type=int) or 50
    per_page = min(max(per_page, 1), 200)
    order_col = getattr(model, 'id', None) or list(model.__table__.primary_key.columns)[0]
    pagination = model.query.order_by(order_col).paginate(
        page=page, per_page=per_page, error_out=False
    )
    rows = [_row_to_readable_dict(model, r) for r in pagination.items]
    columns = [c.name for c in model.__table__.columns]
    return render_template(
        'admin/database_table.html',
        label=label,
        tablename=tablename,
        columns=columns,
        rows=rows,
        pagination=pagination,
    )


# ---------- 仪表盘 ----------
@admin_bp.route('/admin')
@login_required
@admin_required
def admin_dashboard():
    from sqlalchemy import func as SAfunc
    total_orders = Order.query.count()
    paid_orders = Order.query.filter_by(is_paid=True)
    pending_orders = Order.query.filter_by(status='pending').count()
    processing_orders = Order.query.filter_by(status='processing').count()
    total_users = User.query.count()
    banned_users = User.query.filter_by(is_banned=True).count()
    product_count = Product.query.count()
    today = datetime.utcnow().date()
    today_start = datetime(today.year, today.month, today.day)
    revenue_total_due = float(paid_orders.with_entities(SAfunc.sum(Order.amount_due)).scalar() or 0)
    revenue_total_paid = float(paid_orders.with_entities(SAfunc.sum(Order.amount_paid)).scalar() or 0)
    receivable_pending = float(Order.query.filter_by(is_paid=False).with_entities(SAfunc.sum(Order.amount_due)).scalar() or 0)
    today_orders = Order.query.filter(Order.created_at >= today_start).count()
    today_revenue_due = float(paid_orders.filter(Order.paid_at >= today_start).with_entities(SAfunc.sum(Order.amount_due)).scalar() or 0)
    today_revenue_paid = float(paid_orders.filter(Order.paid_at >= today_start).with_entities(SAfunc.sum(Order.amount_paid)).scalar() or 0)
    unread_user_msgs = ChatMessage.query.filter_by(sender='user', is_read_by_admin=False).count()
    top_rows = db.session.query(
        Product.title, SAfunc.coalesce(SAfunc.sum(OrderItem.qty), 0).label('qty')
    ).join(OrderItem, OrderItem.product_id == Product.id).join(Order, OrderItem.order_id == Order.id).filter(
        Order.is_paid == True
    ).group_by(Product.id).order_by(SAfunc.sum(OrderItem.qty).desc()).limit(5).all()
    current_version = Version.query.filter_by(is_current=True).first()
    return render_template(
        'admin/dashboard.html',
        total_orders=total_orders,
        paid_orders=paid_orders.count(),
        pending_orders=pending_orders,
        processing_orders=processing_orders,
        total_users=total_users,
        banned_users=banned_users,
        product_count=product_count,
        revenue_total_due=float(revenue_total_due),
        revenue_total_paid=float(revenue_total_paid),
        receivable_pending=float(receivable_pending),
        today_orders=today_orders,
        today_revenue_due=float(today_revenue_due),
        today_revenue_paid=float(today_revenue_paid),
        unread_user_msgs=unread_user_msgs,
        top_rows=top_rows,
        current_version=current_version,
        now=datetime.utcnow()
    )


# ---------- 商品 ----------
@admin_bp.route('/admin/products/<int:product_id>/stats')
@login_required
@admin_required
def admin_product_stats(product_id: int):
    p = Product.query.get_or_404(product_id)
    rows = db.session.query(
        OrderItem.variant_name.label('vname'),
        func.count(func.distinct(OrderItem.order_id)).label('order_count'),
        func.coalesce(func.sum(OrderItem.qty), 0).label('total_qty')
    ).join(Order, OrderItem.order_id == Order.id).filter(
        OrderItem.product_id == p.id, Order.is_paid == True
    ).group_by(OrderItem.variant_name).all()
    order_rows = db.session.query(OrderItem.variant_name, OrderItem.order_id).join(
        Order, OrderItem.order_id == Order.id
    ).filter(OrderItem.product_id == p.id, Order.is_paid == True).group_by(OrderItem.variant_name, OrderItem.order_id).all()
    order_ids = list({oid for _, oid in order_rows})
    order_no_map = {o.id: o.order_no for o in Order.query.filter(Order.id.in_(order_ids)).all()} if order_ids else {}
    order_map = {}
    for vname, oid in order_rows:
        order_map.setdefault(vname or '', []).append(order_no_map.get(oid, ''))
    detail = []
    total_profit = 0.0
    for vname, order_count, total_qty in rows:
        qty = int(total_qty or 0)
        paid_items = db.session.query(OrderItem.qty, OrderItem.unit_price, OrderItem.unit_cost).join(
            Order, OrderItem.order_id == Order.id
        ).filter(
            OrderItem.product_id == p.id, Order.is_paid == True, OrderItem.variant_name == (vname)
        ).all()
        unit_profit_example = None
        profit = 0.0
        for q, up, uc in paid_items:
            upf, ucf = float(up or 0), float(uc or 0)
            if unit_profit_example is None and (up is not None or uc is not None):
                unit_profit_example = upf - ucf
            profit += (upf - ucf) * int(q or 0)
        if unit_profit_example is None and qty > 0:
            unit_profit_example = profit / qty
        total_profit += profit
        detail.append({
            'name': vname or '（未选规格）',
            'order_count': int(order_count or 0),
            'total_qty': qty,
            'unit_profit': unit_profit_example if unit_profit_example is not None else 0.0,
            'profit': profit,
            'orders': order_map.get(vname or '', [])
        })
    return render_template('admin/product_stats.html', p=p, detail=detail, total_profit=total_profit)


def _upload_folder():
    return current_app.config['UPLOAD_FOLDER']


@admin_bp.route('/admin/products')
@login_required
@admin_required
def admin_products():
    status_order = db.case((Product.status == 'down', 1), else_=0)
    sub_orders = db.session.query(
        OrderItem.product_id.label('pid'),
        func.count(func.distinct(OrderItem.order_id)).label('order_count'),
        func.coalesce(func.sum(OrderItem.qty), 0).label('total_qty')
    ).join(Order, OrderItem.order_id == Order.id).filter(Order.is_paid == True).group_by(OrderItem.product_id).subquery()
    variant_qty_rows = db.session.query(
        OrderItem.product_id, OrderItem.variant_name, func.coalesce(func.sum(OrderItem.qty), 0)
    ).join(Order, OrderItem.order_id == Order.id).filter(Order.is_paid == True).group_by(
        OrderItem.product_id, OrderItem.variant_name
    ).all()
    qty_by_variant = {}
    for pid, vname, q in variant_qty_rows:
        qty_by_variant.setdefault(pid, {})[vname or ''] = int(q or 0)
    rows = db.session.query(Product, sub_orders.c.order_count, sub_orders.c.total_qty).outerjoin(
        sub_orders, Product.id == sub_orders.c.pid
    ).order_by(db.desc(Product.pinned), status_order.asc(), Product.updated_at.desc()).all()
    product_ids = [p.id for p, _, _ in rows]
    profit_data = {}
    if product_ids:
        for row in db.session.query(
            OrderItem.product_id,
            func.sum((OrderItem.unit_price - OrderItem.unit_cost) * OrderItem.qty).label('total_profit')
        ).join(Order, OrderItem.order_id == Order.id).filter(
            OrderItem.product_id.in_(product_ids), Order.is_paid == True
        ).group_by(OrderItem.product_id).all():
            profit_data[row.product_id] = float(row.total_profit or 0)
    enriched = []
    total_profit_all = 0.0
    for p, order_count, total_qty in rows:
        profit = profit_data.get(p.id, 0.0)
        total_profit_all += profit
        enriched.append({
            'product': p,
            'order_count': int(order_count or 0),
            'total_qty': int(total_qty or 0),
            'total_profit': profit
        })
    return render_template('admin/products.html', products=enriched, total_profit=total_profit_all)


@admin_bp.route('/admin/products/new', methods=['GET', 'POST'])
@login_required
@admin_required
def admin_new_product():
    if request.method == 'POST':
        title = request.form['title']
        note = request.form.get('note', '')
        status = request.form.get('status', 'up')
        uploaded_images = []
        if 'images' in request.files:
            uf = _upload_folder()
            for file in request.files.getlist('images'):
                if file and file.filename and allowed_file(file.filename):
                    filename = datetime.now().strftime('%Y%m%d_%H%M%S_') + secure_filename(file.filename)
                    file.save(os.path.join(uf, 'products', filename))
                    uploaded_images.append(f'products/{filename}')
        variants_text = request.form.get('variants_text', '').strip()
        raw_list = []
        try:
            raw_list = json.loads(variants_text) if variants_text else []
        except Exception:
            raw_list = []
        prices = [float(x.get('price') or 0) for x in raw_list if (x.get('price') is not None)]
        costs = [float(x.get('cost') or 0) for x in raw_list if (x.get('cost') is not None)]
        base_price = min(prices) if prices else 0.0
        base_cost = min(costs) if costs else 0.0
        product = Product(
            title=title, price_rmb=base_price, cost_price_rmb=base_cost,
            note=note, status=status,
            images=json.dumps(uploaded_images) if uploaded_images else None,
        )
        db.session.add(product)
        db.session.flush()
        uf = _upload_folder()
        for idx, x in enumerate(raw_list):
            name = (x.get('name') or '').strip()[:100]
            price = float(x.get('price') or 0)
            extra = price - base_price
            stock = max(0, int(x.get('stock') or 0))
            image_rel = None
            f = request.files.get(f'v_image_{idx}')
            if f and f.filename and allowed_file(f.filename):
                fname = datetime.now().strftime('%Y%m%d_%H%M%S_') + secure_filename(f.filename)
                f.save(os.path.join(uf, 'products', fname))
                image_rel = f'products/{fname}'[:512]
            pv = ProductVariant(
                product_id=product.id, local_id=idx + 1, name=name, extra_price=extra,
                image=image_rel, sort_order=idx, stock=stock,
            )
            db.session.add(pv)
        db.session.commit()
        flash('商品创建成功', 'success')
        return redirect(url_for('admin.admin_products'))
    return render_template('admin/product_form.html')


@admin_bp.route('/admin/products/<int:product_id>/edit', methods=['GET', 'POST'])
@login_required
@admin_required
def admin_edit_product(product_id):
    product = Product.query.get_or_404(product_id)
    if request.method == 'POST':
        try:
            if 'title' not in request.form and 'price_rmb' not in request.form:
                new_status = request.form.get('status')
                if new_status in ['up', 'down']:
                    product.status = new_status
                    db.session.commit()
                    flash('商品状态已更新', 'success')
                    return redirect(url_for('admin.admin_products'))
            product.title = request.form.get('title', product.title)
            product.note = request.form.get('note', '')
            product.status = request.form.get('status', 'up')
            variants_text = request.form.get('variants_text', '').strip()
            raw_list = []
            try:
                raw_list = json.loads(variants_text) if variants_text else []
            except Exception:
                raw_list = []
            ProductVariant.query.filter_by(product_id=product.id).delete()
            if raw_list:
                prices = [float(x.get('price') or 0) for x in raw_list if (x.get('price') is not None)]
                costs = [float(x.get('cost') or 0) for x in raw_list if (x.get('cost') is not None)]
                base_price = min(prices) if prices else 0.0
                base_cost = min(costs) if costs else 0.0
                product.price_rmb = base_price
                product.cost_price_rmb = base_cost
                uf = _upload_folder()
                for idx, x in enumerate(raw_list):
                    name = (x.get('name') or '').strip()[:100]
                    price = float(x.get('price') or 0)
                    extra = price - base_price
                    stock = max(0, int(x.get('stock') or 0))
                    image_rel = x.get('image_existing') or request.form.get(f'v_image_existing_{idx}')
                    f = request.files.get(f'v_image_{idx}')
                    if f and f.filename and allowed_file(f.filename):
                        fname = datetime.now().strftime('%Y%m%d_%H%M%S_') + secure_filename(f.filename)
                        f.save(os.path.join(uf, 'products', fname))
                        image_rel = f'products/{fname}'[:512]
                    pv = ProductVariant(
                        product_id=product.id, local_id=idx + 1, name=name, extra_price=extra,
                        image=image_rel[:512] if image_rel else None, sort_order=idx, stock=stock,
                    )
                    db.session.add(pv)
            if 'images' in request.files:
                new_images = []
                uf = _upload_folder()
                for file in request.files.getlist('images'):
                    if file and file.filename and allowed_file(file.filename):
                        filename = datetime.now().strftime('%Y%m%d_%H%M%S_') + secure_filename(file.filename)
                        file.save(os.path.join(uf, 'products', filename))
                        new_images.append(f'products/{filename}')
                if new_images:
                    all_images = product.images_list + new_images
                    product.images = json.dumps(all_images)
            db.session.commit()
            flash('商品更新成功', 'success')
            return redirect(url_for('admin.admin_products'))
        except Exception as e:
            db.session.rollback()
            flash(f'保存失败：{e}', 'error')
            return render_template('admin/product_form.html', product=product)
    return render_template('admin/product_form.html', product=product)


@admin_bp.post('/admin/products/<int:product_id>/delete-image')
@login_required
@admin_required
def admin_product_delete_image(product_id):
    product = Product.query.get_or_404(product_id)
    image_url = request.form.get('image_url')
    if not image_url:
        return redirect(url_for('admin.admin_edit_product', product_id=product.id))
    try:
        imgs = product.images_list
        if image_url in imgs:
            imgs.remove(image_url)
            product.images = json.dumps(imgs)
            uf = _upload_folder()
            abs_path = os.path.join(uf, image_url.replace('/', os.sep))
            if os.path.exists(abs_path):
                try:
                    os.remove(abs_path)
                except Exception:
                    pass
            db.session.commit()
            flash('图片已删除', 'success')
    except Exception as e:
        flash(f'删除失败: {e}', 'error')
    return redirect(url_for('admin.admin_edit_product', product_id=product.id))


@admin_bp.post('/admin/products/<int:product_id>/pin')
@login_required
@admin_required
def admin_product_pin(product_id: int):
    p = Product.query.get_or_404(product_id)
    p.pinned = True
    p.updated_at = datetime.utcnow()
    db.session.commit()
    flash('已置顶该商品', 'success')
    return redirect(url_for('admin.admin_products'))


@admin_bp.post('/admin/products/<int:product_id>/images/upload')
@login_required
@admin_required
def admin_product_upload_image(product_id: int):
    product = Product.query.get_or_404(product_id)
    file = request.files.get('image')
    if not file or not file.filename or not allowed_file(file.filename):
        return jsonify({'ok': False, 'msg': '请选择有效图片'}), 400
    try:
        filename = datetime.now().strftime('%Y%m%d_%H%M%S_') + secure_filename(file.filename)
        filepath = os.path.join(_upload_folder(), 'products', filename)
        file.save(filepath)
        rel = f'products/{filename}'
        imgs = product.images_list + [rel]
        product.images = json.dumps(imgs)
        db.session.commit()
        return jsonify({'ok': True, 'url': url_for('static', filename='uploads/' + rel), 'rel': rel})
    except Exception as e:
        db.session.rollback()
        return jsonify({'ok': False, 'msg': str(e)}), 500


@admin_bp.post('/admin/products/<int:product_id>/delete')
@login_required
@admin_required
def admin_product_delete(product_id: int):
    product = Product.query.get_or_404(product_id)
    try:
        CartItem.query.filter_by(product_id=product.id).delete()
        for oi in OrderItem.query.filter_by(product_id=product.id).all():
            oi.product_id = None
        uf = _upload_folder()
        for rel in product.images_list:
            abs_path = os.path.join(uf, rel.replace('/', os.sep))
            if os.path.exists(abs_path):
                try:
                    os.remove(abs_path)
                except Exception:
                    pass
        for v in product.variants_list:
            rel = v.get('image')
            if rel:
                abs_path = os.path.join(uf, rel.replace('/', os.sep))
                if os.path.exists(abs_path):
                    try:
                        os.remove(abs_path)
                    except Exception:
                        pass
        db.session.delete(product)
        db.session.commit()
        flash('商品已删除', 'success')
        return redirect(url_for('admin.admin_products'))
    except Exception as e:
        db.session.rollback()
        flash(f'删除失败：{e}', 'error')
        return redirect(url_for('admin.admin_edit_product', product_id=product.id))


# ---------- 用户 ----------
@admin_bp.route('/admin/users')
@login_required
@admin_required
def admin_users():
    users = User.query.order_by(User.created_at.desc()).all()
    return render_template('admin/users.html', users=users)


@admin_bp.route('/admin/users/new', methods=['GET', 'POST'])
@login_required
@admin_required
def admin_user_new():
    if request.method == 'POST':
        email = request.form.get('email', '').strip()
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '').strip()
        notes = request.form.get('notes', '').strip()
        name = request.form.get('name', '').strip()
        phone = request.form.get('phone', '').strip()
        address_text = request.form.get('address_text', '').strip()
        postal_code = request.form.get('postal_code', '').strip()
        if not is_valid_email(email):
            flash('邮箱格式不正确', 'error')
            return render_template('admin/user_new.html', form=request.form)
        if not password or len(password) < 6:
            flash('请设置长度至少为6位的密码', 'error')
            return render_template('admin/user_new.html', form=request.form)
        if User.query.filter_by(email=email).first():
            flash('该邮箱已被注册', 'error')
            return render_template('admin/user_new.html', form=request.form)
        if username:
            import re
            if not re.match(r'^[a-zA-Z0-9_]{3,20}$', username):
                flash('用户名只能包含字母、数字和下划线，长度3-20位', 'error')
                return render_template('admin/user_new.html', form=request.form)
            if User.query.filter_by(username=username).first():
                flash('该用户名已被使用', 'error')
                return render_template('admin/user_new.html', form=request.form)
        user = User(
            email=email, username=username if username else None,
            password_hash=generate_password_hash(password), notes=notes if notes else None
        )
        db.session.add(user)
        db.session.flush()
        if name and phone and address_text:
            db.session.add(Address(
                user_id=user.id, name=name, phone=phone,
                address_text=address_text, postal_code=postal_code
            ))
        db.session.commit()
        flash('用户已创建', 'success')
        return redirect(url_for('admin.admin_users'))
    return render_template('admin/user_new.html')


@admin_bp.route('/admin/users/<int:user_id>/edit', methods=['GET', 'POST'])
@login_required
@admin_required
def admin_user_edit(user_id: int):
    user = User.query.get_or_404(user_id)
    if request.method == 'POST':
        email = request.form['email'].strip()
        username = request.form.get('username', '').strip()
        notes = request.form.get('notes', '').strip()
        new_password = request.form.get('password', '').strip()
        if not is_valid_email(email):
            flash('邮箱格式不正确', 'error')
            return render_template('admin/user_form.html', user=user)
        if User.query.filter(User.email == email, User.id != user.id).first():
            flash('该邮箱已被使用', 'error')
            return render_template('admin/user_form.html', user=user)
        if username:
            import re
            if not re.match(r'^[a-zA-Z0-9_]{3,20}$', username):
                flash('用户名只能包含字母、数字和下划线，长度3-20位', 'error')
                return render_template('admin/user_form.html', user=user)
            if User.query.filter(User.username == username, User.id != user.id).first():
                flash('该用户名已被使用', 'error')
                return render_template('admin/user_form.html', user=user)
        user.email = email
        user.username = username if username else None
        user.notes = notes if notes else None
        if new_password:
            user.password_hash = generate_password_hash(new_password)
        db.session.commit()
        flash('用户信息已更新', 'success')
        return redirect(url_for('admin.admin_users'))
    return render_template('admin/user_form.html', user=user)


@admin_bp.route('/admin/users/<int:user_id>/edit-address', methods=['POST'])
@login_required
@admin_required
def admin_user_edit_address(user_id: int):
    user = User.query.get_or_404(user_id)
    name, phone = request.form['name'], request.form['phone']
    address_text, postal_code = request.form['address_text'], request.form.get('postal_code', '')
    if user.address:
        addr = user.address
        addr.name, addr.phone, addr.address_text, addr.postal_code = name, phone, address_text, postal_code
    else:
        db.session.add(Address(user_id=user.id, name=name, phone=phone, address_text=address_text, postal_code=postal_code))
    db.session.commit()
    flash('地址已保存', 'success')
    return redirect(url_for('admin.admin_user_edit', user_id=user.id))


@admin_bp.route('/admin/users/<int:user_id>/delete', methods=['POST'])
@login_required
@admin_required
def admin_user_delete(user_id: int):
    user = User.query.get_or_404(user_id)
    if user.address:
        db.session.delete(user.address)
    for order in list(user.orders):
        for item in list(order.items):
            db.session.delete(item)
        for att in list(order.payment_attachments):
            db.session.delete(att)
        db.session.delete(order)
    db.session.delete(user)
    db.session.commit()
    flash('用户已删除', 'success')
    return redirect(url_for('admin.admin_users'))


@admin_bp.route('/admin/users/<int:user_id>/ban')
@login_required
@admin_required
def admin_user_ban(user_id: int):
    user = User.query.get_or_404(user_id)
    user.is_banned = True
    db.session.commit()
    flash('已封禁该用户', 'success')
    return redirect(url_for('admin.admin_users'))


@admin_bp.route('/admin/users/<int:user_id>/unban')
@login_required
@admin_required
def admin_user_unban(user_id: int):
    user = User.query.get_or_404(user_id)
    user.is_banned = False
    db.session.commit()
    flash('已解封该用户', 'success')
    return redirect(url_for('admin.admin_users'))


# ---------- 订单 ----------
@admin_bp.route('/admin/orders')
@login_required
@admin_required
def admin_orders():
    status_filter = request.args.get('status', 'all')
    paid_filter = request.args.get('paid', 'all')
    search = request.args.get('search', '')
    start_date = request.args.get('start_date')
    end_date = request.args.get('end_date')
    orders_query = Order.query
    if status_filter != 'all':
        orders_query = orders_query.filter_by(status=status_filter)
    if paid_filter == 'paid':
        orders_query = orders_query.filter_by(is_paid=True)
    elif paid_filter == 'unpaid':
        orders_query = orders_query.filter_by(is_paid=False)
    if start_date:
        try:
            orders_query = orders_query.filter(Order.created_at >= datetime.strptime(start_date + ' 00:00:00', '%Y-%m-%d %H:%M:%S'))
        except Exception:
            pass
    if end_date:
        try:
            orders_query = orders_query.filter(Order.created_at <= datetime.strptime(end_date + ' 23:59:59', '%Y-%m-%d %H:%M:%S'))
        except Exception:
            pass
    if search:
        like = f"%{search}%"
        orders_query = orders_query.join(User).filter(
            db.or_(Order.order_no.like(like), User.email.like(like), Order.cancel_reason.like(like))
        )
    orders_list = orders_query.order_by(Order.created_at.desc()).all()
    return render_template(
        'admin/orders.html',
        orders=orders_list,
        status_filter=status_filter, paid_filter=paid_filter, search=search,
        start_date=start_date or '', end_date=end_date or ''
    )


@admin_bp.route('/admin/orders/new', methods=['GET', 'POST'])
@login_required
@admin_required
def admin_new_order():
    if request.method == 'POST':
        user_email = request.form['user_email']
        amount_items = float(request.form['amount_items'])
        amount_shipping = float(request.form['amount_shipping'])
        user = User.query.filter_by(email=user_email).first()
        if not user:
            temp_password = ''.join(random.choices(string.ascii_letters + string.digits, k=8))
            user = User(email=user_email, password_hash=generate_password_hash(temp_password))
            db.session.add(user)
            db.session.flush()
        order_no = generate_order_no()
        order = Order(
            order_no=order_no, user_id=user.id,
            amount_items=amount_items, amount_shipping=amount_shipping,
            amount_due=amount_items + amount_shipping
        )
        db.session.add(order)
        db.session.flush()
        item_names = request.form.getlist('item_name')
        item_specs = request.form.getlist('item_spec')
        item_qtys = request.form.getlist('item_qty')
        for name, spec, qty in zip(item_names, item_specs, item_qtys):
            if not name:
                continue
            qty = int(qty or 1)
            db.session.add(OrderItem(
                order_id=order.id, name=name.strip(), spec_note=(spec or '').strip(),
                qty=qty, unit_price=0, unit_cost=0
            ))
        db.session.commit()
        flash(f'订单 {order_no} 已创建', 'success')
        return redirect(url_for('admin.admin_order_detail', order_no=order_no))
    return render_template('admin/order_form.html', products=Product.query.filter_by(status='up').all())


@admin_bp.route('/admin/orders/<order_no>')
@login_required
@admin_required
def admin_order_detail(order_no):
    order = Order.query.filter_by(order_no=order_no).first_or_404()
    fill_order_items_unit_price(order)
    return render_template('admin/order_detail.html', order=order)


@admin_bp.route('/admin/orders/<order_no>/mark-paid', methods=['POST'])
@login_required
@admin_required
def admin_mark_paid(order_no):
    order = Order.query.filter_by(order_no=order_no).first_or_404()
    try:
        amount_paid = float(request.form.get('amount_paid') or order.amount_due or 0)
    except Exception:
        amount_paid = float(order.amount_due or 0)
    order.amount_paid = amount_paid
    order.is_paid = True
    order.paid_at = datetime.utcnow()
    order.status = 'processing'
    db.session.commit()
    try:
        send_email(
            f"订单 {order_no} 付款确认",
            f"亲爱的 {order.user.email}，\n\n您的订单 {order_no} 付款已确认，订单状态已更新为\"处理中\"。\n\n订单详情：\n- 订单号：{order_no}\n- 合计：¥{order.amount_due}\n\n感谢您的信任！",
            order.user.email
        )
    except Exception as e:
        logger.warning("标记已付款后邮件发送失败: %s", e)
    flash('订单已标记为已付款', 'success')
    return redirect(url_for('admin.admin_order_detail', order_no=order_no))


@admin_bp.route('/admin/orders/<order_no>/mark-unpaid', methods=['POST'])
@login_required
@admin_required
def admin_mark_unpaid(order_no):
    order = Order.query.filter_by(order_no=order_no).first_or_404()
    order.is_paid = False
    order.paid_at = None
    order.status = 'pending'
    order.amount_paid = 0
    db.session.commit()
    flash('订单已标记为未付款', 'success')
    return redirect(url_for('admin.admin_order_detail', order_no=order_no))


@admin_bp.route('/admin/orders/<order_no>/status', methods=['POST'])
@login_required
@admin_required
def admin_update_status(order_no):
    order = Order.query.filter_by(order_no=order_no).first_or_404()
    new_status = request.form['status']
    reason = request.form.get('reason', '')
    old_status = order.status
    order.status = new_status
    if new_status == 'done':
        order.completed_at = datetime.utcnow()
    elif new_status == 'canceled':
        order.canceled_at = datetime.utcnow()
        order.cancel_reason = reason
        restore_order_stock(order)
    db.session.commit()
    try:
        status_names = {'pending': '待支付', 'processing': '处理中', 'done': '已完成', 'canceled': '已取消'}
        send_email(
            f"订单 {order_no} 状态更新",
            f"亲爱的 {order.user.email}，\n\n您的订单 {order_no} 状态已更新：{status_names.get(old_status, old_status)} -> {status_names.get(new_status, new_status)}\n\n感谢您的购买！",
            order.user.email
        )
    except Exception as e:
        logger.warning("订单状态更新后邮件发送失败: %s", e)
    flash(f'订单状态已更新为：{new_status}', 'success')
    return redirect(url_for('admin.admin_order_detail', order_no=order_no))


def _purchase_list_filters(orders_q, start_date, end_date, keyword):
    """对订单查询应用日期与关键词筛选。"""
    if start_date:
        try:
            orders_q = orders_q.filter(Order.created_at >= datetime.strptime(start_date + ' 00:00:00', '%Y-%m-%d %H:%M:%S'))
        except Exception:
            pass
    if end_date:
        try:
            orders_q = orders_q.filter(Order.created_at <= datetime.strptime(end_date + ' 23:59:59', '%Y-%m-%d %H:%M:%S'))
        except Exception:
            pass
    if keyword:
        like = f"%{keyword}%"
        orders_q = orders_q.join(User).filter(db.or_(Order.order_no.like(like), User.email.like(like)))
    return orders_q


@admin_bp.route('/admin/purchase-list', methods=['GET'])
@login_required
@admin_required
def admin_purchase_preview():
    start_date = request.args.get('start_date')
    end_date = request.args.get('end_date')
    keyword = request.args.get('q', '')
    # 待发货：已付款、处理中、未发货，按「同一天+同一用户」聚合（同批发往同一地址）
    pending_q = Order.query.filter(
        Order.is_paid == True,
        Order.status == 'processing',
        Order.shipped_at.is_(None),
    )
    pending_q = _purchase_list_filters(pending_q, start_date, end_date, keyword)
    pending_orders = pending_q.order_by(Order.created_at.asc()).all()
    from collections import defaultdict
    groups = defaultdict(list)
    for o in pending_orders:
        key = (o.created_at.date() if o.created_at else None, o.user_id)
        groups[key].append(o)
    pending_groups = []
    product_ids = set()
    for (day, uid), orders in sorted(groups.items(), key=lambda x: (x[0][0] or datetime.min.date(), x[0][1])):
        o0 = orders[0]
        user, addr = o0.user, o0.user.address
        for o in orders:
            for it in o.items:
                if it.product_id:
                    product_ids.add(it.product_id)
        pending_groups.append({
            'date': day,
            'user': user,
            'address': addr,
            'orders': orders,
            'order_nos': [o.order_no for o in orders],
        })
    title_map = product_id_to_title_map(product_ids) if product_ids else {}
    # 已发货：已填写快递并标记发货的订单
    shipped_q = Order.query.filter(
        Order.is_paid == True,
        Order.shipped_at.isnot(None),
    )
    shipped_q = _purchase_list_filters(shipped_q, start_date, end_date, keyword)
    shipped_orders = shipped_q.order_by(Order.shipped_at.desc()).all()
    return render_template(
        'admin/purchase_preview.html',
        pending_groups=pending_groups,
        title_map=title_map,
        shipped_orders=shipped_orders,
        start_date=start_date or '',
        end_date=end_date or '',
        keyword=keyword,
    )


def _purchase_preview_redirect(start_date=None, end_date=None, keyword=None):
    """带筛选参数的发货清单重定向。"""
    kwargs = {}
    if start_date is not None and start_date != '':
        kwargs['start_date'] = start_date
    if end_date is not None and end_date != '':
        kwargs['end_date'] = end_date
    if keyword is not None and keyword != '':
        kwargs['q'] = keyword
    return redirect(url_for('admin.admin_purchase_preview', **kwargs))


@admin_bp.route('/admin/orders/mark-shipped', methods=['POST'])
@login_required
@admin_required
def admin_orders_mark_shipped():
    """将一批订单标记为已发货，填写快递号并发送邮件。"""
    order_ids = request.form.getlist('order_id', type=int)
    tracking = (request.form.get('tracking_number') or '').strip()
    start_date = request.form.get('start_date') or ''
    end_date = request.form.get('end_date') or ''
    keyword = request.form.get('keyword') or ''
    if not order_ids:
        flash('请选择要发货的订单', 'error')
        return _purchase_preview_redirect(start_date, end_date, keyword)
    if not tracking:
        flash('请填写快递单号', 'error')
        return _purchase_preview_redirect(start_date, end_date, keyword)
    orders = Order.query.filter(Order.id.in_(order_ids), Order.is_paid == True, Order.shipped_at.is_(None)).all()
    if not orders:
        flash('未找到可发货的订单或订单已发货', 'error')
        return _purchase_preview_redirect(start_date, end_date, keyword)
    now = datetime.utcnow()
    for o in orders:
        o.tracking_number = tracking[:100]
        o.shipped_at = now
        o.status = 'done'
        o.completed_at = now
        try:
            send_email(
                f"您的订单 {o.order_no} 已发货",
                f"您好，\n\n您的订单 {o.order_no} 已发货。\n快递单号：{tracking}\n\n请留意查收。",
                o.user.email,
            )
        except Exception as e:
            logger.warning("发货通知邮件发送失败 %s: %s", o.user.email, e)
    db.session.commit()
    flash(f'已标记 {len(orders)} 个订单为已发货，快递单号：{tracking}，已发送邮件通知', 'success')
    return _purchase_preview_redirect(start_date, end_date, keyword)


@admin_bp.route('/admin/purchase-list/download', methods=['GET'])
@login_required
@admin_required
def admin_purchase_download():
    start_date = request.args.get('start_date')
    end_date = request.args.get('end_date')
    keyword = request.args.get('q', '')
    status = request.args.get('status', 'processing')
    orders_q = Order.query.filter(Order.is_paid == True)
    if status != 'all':
        orders_q = orders_q.filter(Order.status == 'processing')
    if start_date:
        try:
            orders_q = orders_q.filter(Order.created_at >= datetime.strptime(start_date + ' 00:00:00', '%Y-%m-%d %H:%M:%S'))
        except Exception:
            pass
    if end_date:
        try:
            orders_q = orders_q.filter(Order.created_at <= datetime.strptime(end_date + ' 23:59:59', '%Y-%m-%d %H:%M:%S'))
        except Exception:
            pass
    if keyword:
        like = f"%{keyword}%"
        orders_q = orders_q.join(User).filter(db.or_(Order.order_no.like(like), User.email.like(like)))
    orders_list = orders_q.order_by(Order.created_at.asc()).all()
    product_ids = {item.product_id for order in orders_list for item in order.items if item.product_id}
    title_map = product_id_to_title_map(product_ids)
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['订单号', '下单时间', '用户邮箱', '收货人', '手机号', '地址', '商品名称', '规格', '数量', '来源'])
    for order in orders_list:
        user, addr = order.user, order.user.address
        receiver = addr.name if addr else ''
        phone = addr.phone if addr else ''
        addr_text = addr.address_text if addr else ''
        for item in order.items:
            display_name = title_map.get(item.product_id, item.name) if item.product_id else item.name
            spec = item.variant_name or item.spec_note or ''
            writer.writerow([
                order.order_no, order.created_at.strftime('%Y-%m-%d %H:%M:%S'), user.email,
                receiver, phone, addr_text, display_name, spec, item.qty,
                '商品库' if item.product_id else '自定义'
            ])
    output.seek(0)
    parts = [datetime.utcnow().strftime('%Y%m%d')]
    if start_date or end_date:
        parts.append(f"{start_date or 'begin'}-to-{end_date or 'end'}")
    if keyword:
        parts.append(f"q-{keyword}")
    filename = 'ship_' + '_'.join(parts) + '.csv'
    from flask import Response
    return Response(
        output.getvalue(),
        mimetype='text/csv',
        headers={'Content-Disposition': f'attachment; filename={filename}'}
    )


# ---------- 仓储可视化 ----------
def _warehouse_sales_trend(cutoff):
    """过去某段时间内已付款订单的销量：按商品、规格聚合，返回 [(product_title, variant_name, qty), ...] 按销量降序。"""
    rows = db.session.query(
        OrderItem.product_id,
        OrderItem.variant_id,
        func.sum(OrderItem.qty).label('qty'),
        func.max(OrderItem.variant_name).label('vname'),
        func.max(OrderItem.name).label('item_name'),
    ).join(Order, OrderItem.order_id == Order.id).filter(
        Order.is_paid == True,
        db.func.coalesce(Order.paid_at, Order.created_at) >= cutoff,
    ).group_by(OrderItem.product_id, OrderItem.variant_id).order_by(func.sum(OrderItem.qty).desc()).limit(10).all()
    product_ids = {r.product_id for r in rows if r.product_id}
    variant_ids = {r.variant_id for r in rows if r.variant_id}
    title_map = product_id_to_title_map(product_ids) if product_ids else {}
    variant_map = {v.id: v.name for v in ProductVariant.query.filter(ProductVariant.id.in_(variant_ids)).all()} if variant_ids else {}
    out = []
    for r in rows:
        product_title = title_map.get(r.product_id) if r.product_id else (r.item_name or '自定义')
        variant_name = variant_map.get(r.variant_id) if r.variant_id else (r.vname or r.item_name or '—')
        out.append({
            'product_id': r.product_id,
            'variant_id': r.variant_id,
            'product_title': product_title,
            'variant_name': variant_name,
            'qty': int(r.qty or 0),
        })
    return out


@admin_bp.route('/admin/warehouse')
@login_required
@admin_required
def admin_warehouse():
    """仓储可视化：按商品展示所有规格及库存；趋势：近 1/7/30 天销量。"""
    products = Product.query.order_by(Product.pinned.desc(), Product.updated_at.desc()).all()
    total_variants = 0
    total_stock = 0
    product_rows = []
    for p in products:
        variants = sorted(p.product_variants, key=lambda x: (x.sort_order, x.id))
        total_variants += len(variants)
        product_stock = sum((v.stock or 0) for v in variants)
        total_stock += product_stock
        product_rows.append({
            'product': p,
            'variants': variants,
            'product_stock': product_stock,
        })
    now = datetime.utcnow()
    trend_1d = _warehouse_sales_trend(now - timedelta(days=1))
    trend_7d = _warehouse_sales_trend(now - timedelta(days=7))
    trend_30d = _warehouse_sales_trend(now - timedelta(days=30))
    return render_template(
        'admin/warehouse.html',
        product_rows=product_rows,
        total_variants=total_variants,
        total_stock=total_stock,
        trend_1d=trend_1d,
        trend_7d=trend_7d,
        trend_30d=trend_30d,
    )


# ---------- 设置 ----------
@admin_bp.route('/admin/settings')
@login_required
@admin_required
def admin_settings():
    return render_template(
        'admin/settings.html',
        alipay_qr=get_setting('alipay_qrcode'),
        wechat_qr=get_setting('wechat_qrcode'),
        auto_cancel_enabled=get_setting('auto_cancel_enabled', 'true'),
        auto_cancel_hours=get_setting('auto_cancel_hours', '24')
    )


@admin_bp.route('/admin/basic-settings', methods=['GET', 'POST'])
@login_required
@admin_required
def admin_basic_settings():
    if request.method == 'POST':
        set_setting('site_title', request.form.get('site_title', '').strip() or 'Moly代购网站')
        set_setting('footer_text', request.form.get('footer_text', '').strip() or '保留所有权利.')
        if request.form.get('cover_image'):
            set_setting('cover_image', request.form.get('cover_image'))
        if request.form.get('wechat_qr'):
            set_setting('wechat_qr', request.form.get('wechat_qr'))
        flash('基础设定已保存', 'success')
        return redirect(url_for('admin.admin_basic_settings'))
    return render_template(
        'admin/basic_settings.html',
        site_title=get_setting('site_title', 'Moly代购网站'),
        footer_text=get_setting('footer_text', '保留所有权利.'),
        cover_image=get_setting('cover_image'),
        wechat_qr=get_setting('wechat_qr')
    )


@admin_bp.route('/admin/settings/cover', methods=['POST'])
@login_required
@admin_required
def admin_update_cover():
    if 'cover' in request.files:
        file = request.files['cover']
        if file and file.filename and allowed_file(file.filename):
            filename = datetime.now().strftime('%Y%m%d_%H%M%S_') + secure_filename(file.filename)
            file.save(os.path.join(_upload_folder(), 'covers', filename))
            set_setting('cover_image', f'covers/{filename}')
            flash('封面已更新', 'success')
        else:
            flash('请选择有效的图片文件', 'error')
    else:
        flash('未选择文件', 'error')
    return redirect(url_for('admin.admin_settings'))


@admin_bp.route('/admin/settings/wechat-qr', methods=['POST'])
@login_required
@admin_required
def admin_update_wechat_qr():
    if 'wechat_qr' in request.files:
        file = request.files['wechat_qr']
        if file and file.filename and allowed_file(file.filename):
            filename = datetime.now().strftime('%Y%m%d_%H%M%S_') + secure_filename(file.filename)
            file.save(os.path.join(_upload_folder(), 'qrcodes', filename))
            set_setting('wechat_qr', f'qrcodes/{filename}')
            flash('微信二维码已更新', 'success')
        else:
            flash('请选择有效的图片文件', 'error')
    else:
        flash('未选择文件', 'error')
    return redirect(url_for('admin.admin_basic_settings'))


@admin_bp.route('/admin/settings/payment-qrcodes', methods=['POST'])
@login_required
@admin_required
def admin_update_qrcodes():
    uf = _upload_folder()
    if 'alipay_qr' in request.files:
        file = request.files['alipay_qr']
        if file and file.filename and allowed_file(file.filename):
            filename = datetime.now().strftime('%Y%m%d_%H%M%S_') + secure_filename(file.filename)
            file.save(os.path.join(uf, 'qrcodes', filename))
            set_setting('alipay_qrcode', f'qrcodes/{filename}')
    if 'wechat_qr' in request.files:
        file = request.files['wechat_qr']
        if file and file.filename and allowed_file(file.filename):
            filename = datetime.now().strftime('%Y%m%d_%H%M%S_') + secure_filename(file.filename)
            file.save(os.path.join(uf, 'qrcodes', filename))
            set_setting('wechat_qrcode', f'qrcodes/{filename}')
    flash('收款二维码更新成功', 'success')
    return redirect(url_for('admin.admin_settings'))


@admin_bp.route('/admin/settings/order-rules', methods=['POST'])
@login_required
@admin_required
def admin_update_order_rules():
    set_setting('auto_cancel_enabled', request.form.get('auto_cancel_enabled', 'false'))
    set_setting('auto_cancel_hours', request.form.get('auto_cancel_hours', '24'))
    flash('订单规则更新成功', 'success')
    return redirect(url_for('admin.admin_settings'))


# ---------- 版本 ----------
@admin_bp.route('/admin/versions')
@login_required
@admin_required
def admin_versions():
    versions = Version.query.order_by(Version.release_date.desc()).all()
    return render_template('admin/versions.html', versions=versions)


@admin_bp.route('/admin/versions/new', methods=['GET', 'POST'])
@login_required
@admin_required
def admin_new_version():
    if request.method == 'POST':
        version = request.form['version']
        title = request.form['title']
        description = request.form['description']
        if Version.query.filter_by(version=version).first():
            flash('该版本号已存在', 'error')
            return render_template('admin/version_form.html')
        is_current = 'is_current' in request.form
        if is_current:
            Version.query.update({'is_current': False})
        new_version = Version(version=version, title=title, description=description, is_current=is_current)
        db.session.add(new_version)
        db.session.commit()
        flash('版本信息添加成功', 'success')
        return redirect(url_for('admin.admin_versions'))
    return render_template('admin/version_form.html')


@admin_bp.route('/admin/versions/<int:version_id>/set-current')
@login_required
@admin_required
def admin_set_current_version(version_id):
    version = Version.query.get_or_404(version_id)
    Version.query.update({'is_current': False})
    version.is_current = True
    db.session.commit()
    flash(f'已将版本 {version.version} 设为当前版本', 'success')
    return redirect(url_for('admin.admin_versions'))


@admin_bp.route('/admin/versions/<int:version_id>/delete')
@login_required
@admin_required
def admin_delete_version(version_id):
    version = Version.query.get_or_404(version_id)
    if version.is_current:
        flash('不能删除当前版本', 'error')
        return redirect(url_for('admin.admin_versions'))
    db.session.delete(version)
    db.session.commit()
    flash('版本信息删除成功', 'success')
    return redirect(url_for('admin.admin_versions'))
