# 前台路由：首页、商品、购物车、登录注册、订单、地址
import json
import os
from datetime import datetime, timedelta

from flask import Blueprint, render_template, request, redirect, url_for, flash, current_app
from flask_login import login_required, login_user, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from sqlalchemy import func

from core.extensions import db
from core.models import (
    User, Address, Product, Order, OrderItem, CartItem,
    PaymentAttachment, EmailVerification,
)
from core.utils import get_setting, allowed_file, generate_order_no, is_valid_email, user_required, fill_order_items_unit_price, restore_order_stock
from services.send_email import send_email

frontend = Blueprint('frontend', __name__)


@frontend.route('/')
def index():
    status_order = db.case((Product.status == 'down', 1), else_=0)
    products = Product.query.filter(Product.status.in_(['up', 'down'])).order_by(
        status_order.asc(), Product.updated_at.desc()
    ).all()
    sales_rows = db.session.query(
        OrderItem.product_id.label('pid'),
        func.coalesce(func.sum(OrderItem.qty), 0).label('total_qty')
    ).join(Order, OrderItem.order_id == Order.id).filter(
        Order.is_paid == True, OrderItem.product_id.isnot(None)
    ).group_by(OrderItem.product_id).all()
    sales_map = {row.pid: int(row.total_qty or 0) for row in sales_rows}
    min_price_map = {p.id: p.get_min_display_price() for p in products}
    return render_template(
        'frontend/index.html',
        products=products,
        sales_map=sales_map,
        min_price_map=min_price_map
    )


@frontend.route('/product/<int:product_id>')
def product_detail(product_id: int):
    p = Product.query.get_or_404(product_id)
    return render_template(
        'frontend/product_detail.html',
        p=p,
        imgs=p.images_list,
        variants=p.variants_list
    )


@frontend.route('/cart')
@login_required
@user_required
def cart_page():
    status_order = db.case((Product.status == 'down', 1), else_=0)
    items = db.session.query(CartItem, Product).join(
        Product, CartItem.product_id == Product.id
    ).filter(CartItem.user_id == current_user.id).order_by(
        status_order.asc(), CartItem.created_at.asc()
    ).all()
    display = []
    for ci, p in items:
        if ci.variant_id and ci.variant:
            unit = ci.variant.get_display_price(p)
        else:
            unit = p.get_variant_price(ci.variant_name)
        display.append({'item': ci, 'product': p, 'unit_price': unit, 'subtotal': unit * ci.qty})
    return render_template('frontend/cart.html', cart_items=display)


@frontend.route('/cart/add/<int:product_id>', methods=['POST'])
@login_required
@user_required
def add_to_cart(product_id: int):
    from core.models import ProductVariant
    product = Product.query.get_or_404(product_id)
    if product.status != 'up':
        flash('该商品未上架，无法加入购物车', 'error')
        return redirect(url_for('frontend.index'))
    qty = max(1, min(int(request.form.get('qty', '1') or '1'), 999))
    variant_id = request.form.get('variant_id', type=int) or None
    variant_name = request.form.get('variant_name') or None
    if variant_id:
        pv = product.get_variant_by_id(variant_id)
        if not pv:
            flash('所选规格无效', 'error')
            return redirect(request.referrer or url_for('frontend.index'))
        if pv.stock is not None and pv.stock < qty:
            flash(f'规格「{pv.name}」库存不足（当前 {pv.stock}），请减少数量或选择其他规格', 'error')
            return redirect(request.referrer or url_for('frontend.index'))
        variant_name = pv.name
    elif variant_name and product.product_variants:
        pv = next((v for v in product.product_variants if v.name == variant_name), None)
        if pv:
            variant_id = pv.id
            if pv.stock is not None and pv.stock < qty:
                flash(f'规格「{pv.name}」库存不足（当前 {pv.stock}），请减少数量或选择其他规格', 'error')
                return redirect(request.referrer or url_for('frontend.index'))
    item = CartItem.query.filter_by(
        user_id=current_user.id, product_id=product_id, variant_id=variant_id
    ).first()
    if not item and variant_name and not variant_id and product.product_variants:
        item = CartItem.query.filter_by(
            user_id=current_user.id, product_id=product_id, variant_name=variant_name
        ).first()
    if item:
        new_qty = item.qty + qty
        if item.variant_id:
            pv = ProductVariant.query.get(item.variant_id)
            if pv and pv.stock is not None and pv.stock < new_qty:
                flash(f'规格「{pv.name}」库存不足（当前 {pv.stock}），最多可加购 {pv.stock} 件', 'error')
                return redirect(request.referrer or url_for('frontend.index'))
        item.qty = new_qty
        if variant_id is not None:
            item.variant_id = variant_id
            item.variant_name = variant_name
    else:
        item = CartItem(
            user_id=current_user.id, product_id=product_id, qty=qty,
            variant_id=variant_id, variant_name=variant_name,
        )
        db.session.add(item)
    db.session.commit()
    vtip = f'（{variant_name}）' if variant_name else ''
    flash(f'"{product.title}{vtip}" ×{qty} 已加入购物车', 'success')
    return redirect(request.referrer or url_for('frontend.index'))


@frontend.route('/cart/update/<int:item_id>', methods=['POST'])
@login_required
@user_required
def update_cart(item_id: int):
    item = CartItem.query.get_or_404(item_id)
    if item.user_id != current_user.id:
        flash('无权操作', 'error')
        return redirect(url_for('frontend.cart_page'))
    qty = int(request.form.get('qty', '1') or '1')
    if qty <= 0:
        db.session.delete(item)
    else:
        item.qty = min(qty, 999)
    db.session.commit()
    return redirect(url_for('frontend.cart_page'))


@frontend.route('/cart/remove/<int:item_id>', methods=['POST'])
@login_required
@user_required
def remove_cart(item_id: int):
    item = CartItem.query.get_or_404(item_id)
    if item.user_id != current_user.id:
        flash('无权操作', 'error')
        return redirect(url_for('frontend.cart_page'))
    db.session.delete(item)
    db.session.commit()
    flash('已移除', 'success')
    return redirect(url_for('frontend.cart_page'))


@frontend.route('/cart/checkout', methods=['POST'])
@login_required
@user_required
def cart_checkout():
    ids = request.form.getlist('item_id')
    if not ids:
        flash('请先选择要结算的商品', 'error')
        return redirect(url_for('frontend.cart_page'))
    addr = getattr(current_user, 'address', None)
    if not addr or not addr.name or not addr.phone or not addr.address_text:
        flash('请先完善收货地址（收货人、手机号、地址），再提交订单', 'error')
        return redirect(url_for('frontend.profile_address'))
    cart_items = db.session.query(CartItem, Product).join(
        Product, CartItem.product_id == Product.id
    ).filter(CartItem.user_id == current_user.id, CartItem.id.in_(ids)).all()
    if not cart_items:
        flash('未找到选中的商品', 'error')
        return redirect(url_for('frontend.cart_page'))
    from core.models import ProductVariant
    invalid = [(ci, p) for (ci, p) in cart_items if p.status != 'up']
    if invalid:
        names = '、'.join([p.title for (ci, p) in invalid])
        flash(f'以下商品已下架，未能提交订单：{names}。请移除或等待上架。', 'error')
        return redirect(url_for('frontend.cart_page'))
    for (ci, p) in cart_items:
        if ci.variant_id:
            pv = ProductVariant.query.get(ci.variant_id)
            if not pv or pv.product_id != p.id:
                flash(f'商品「{p.title}」的规格数据异常，请移除后重新加入购物车', 'error')
                return redirect(url_for('frontend.cart_page'))
            if pv.stock is not None and pv.stock < ci.qty:
                flash(f'规格「{pv.name}」库存不足（当前 {pv.stock}），请调整数量后重试', 'error')
                return redirect(url_for('frontend.cart_page'))
    amount_items = 0.0
    per_item_prices = {}
    for (ci, p) in cart_items:
        if ci.variant_id and ci.variant:
            unit_price = ci.variant.get_display_price(p)
            unit_cost = ci.variant.get_cost()
        else:
            unit_price = p.get_variant_price(ci.variant_name)
            unit_cost = p.get_variant_cost(ci.variant_name)
        per_item_prices[ci.id] = (unit_price, unit_cost)
        amount_items += unit_price * ci.qty
    amount_shipping = 0.0
    order_no = generate_order_no()
    order = Order(
        order_no=order_no,
        user_id=current_user.id,
        amount_items=amount_items,
        amount_shipping=amount_shipping,
        amount_due=amount_items + amount_shipping
    )
    db.session.add(order)
    db.session.flush()
    for (ci, p) in cart_items:
        up, uc = per_item_prices.get(ci.id, (p.get_variant_price(ci.variant_name), p.get_variant_cost(ci.variant_name)))
        oi = OrderItem(
            order_id=order.id,
            product_id=p.id,
            variant_id=ci.variant_id,
            name=p.title,
            spec_note=p.note or '',
            qty=ci.qty,
            variant_name=ci.variant_name or (ci.variant.name if ci.variant else None),
            unit_price=up,
            unit_cost=uc,
        )
        db.session.add(oi)
        if ci.variant_id:
            pv = ProductVariant.query.get(ci.variant_id)
            if pv and pv.product_id == p.id and pv.stock is not None:
                pv.stock = max(0, (pv.stock or 0) - ci.qty)
        db.session.delete(ci)
    db.session.commit()
    flash(f'订单已提交，订单号：{order_no}，请前往订单详情查看并付款', 'success')
    return redirect(url_for('frontend.order_detail', order_no=order_no))


@frontend.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email_or_username = request.form['email'].strip()
        password = request.form['password']
        if '@' in email_or_username:
            user = User.query.filter_by(email=email_or_username).first()
        else:
            user = User.query.filter_by(username=email_or_username).first()
        if user and check_password_hash(user.password_hash, password):
            if user.is_banned:
                flash('您的账户已被封禁，请联系管理员', 'error')
            else:
                login_user(user, remember=True, duration=timedelta(days=7))
                user.last_login_at = datetime.utcnow()
                db.session.commit()
                return redirect(url_for('frontend.index'))
        else:
            flash('邮箱/用户名或密码错误', 'error')
    return render_template('frontend/login.html')


@frontend.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        email = request.form['email']
        username = request.form.get('username', '').strip()
        password = request.form['password']
        code = request.form.get('code', '')
        if not is_valid_email(email):
            flash('邮箱格式不正确', 'error')
            return render_template('frontend/register.html')
        if User.query.filter_by(email=email).first():
            flash('该邮箱已被注册', 'error')
            return render_template('frontend/register.html')
        if username:
            import re
            if not re.match(r'^[a-zA-Z0-9_]{3,20}$', username):
                flash('用户名只能包含字母、数字和下划线，长度3-20位', 'error')
                return render_template('frontend/register.html')
            if User.query.filter_by(username=username).first():
                flash('该用户名已被使用', 'error')
                return render_template('frontend/register.html')
        ver = EmailVerification.query.filter_by(
            email=email, code=code, used=False
        ).order_by(EmailVerification.id.desc()).first()
        if not ver or ver.expire_at < datetime.utcnow():
            flash('验证码无效或已过期', 'error')
            return render_template('frontend/register.html')
        ver.used = True
        db.session.commit()
        user = User(
            email=email,
            username=username if username else None,
            password_hash=generate_password_hash(password)
        )
        db.session.add(user)
        db.session.commit()
        login_user(user, remember=True)
        flash('注册成功，已自动登录', 'success')
        return redirect(url_for('frontend.index'))
    return render_template('frontend/register.html')


@frontend.route('/api/auth/send-code', methods=['POST'])
def send_register_code():
    from flask import jsonify
    data = request.form if request.form else request.get_json(silent=True) or {}
    email = (data.get('email') or '').strip()
    if not is_valid_email(email):
        return jsonify({'code': 400, 'message': '邮箱格式不正确', 'data': None}), 400
    if User.query.filter_by(email=email).first():
        return jsonify({'code': 400, 'message': '该邮箱已被注册', 'data': None}), 400
    EmailVerification.query.filter_by(email=email, used=False).update({'used': True})
    code = ''.join(__import__('random').choices(__import__('string').digits, k=6))
    expire_at = datetime.utcnow() + timedelta(minutes=10)
    rec = EmailVerification(email=email, code=code, expire_at=expire_at)
    db.session.add(rec)
    db.session.commit()
    try:
        send_email('注册验证码', f'您的验证码为：{code}，10分钟内有效。', email)
    except Exception as e:
        print('发送验证码失败: ', e)
        return jsonify({'code': 500, 'message': '验证码发送失败', 'data': None}), 500
    return jsonify({'code': 0, 'message': '验证码已发送', 'data': {'expire_minutes': 10}})


@frontend.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('frontend.index'))


@frontend.route('/profile/address', methods=['GET', 'POST'])
@login_required
@user_required
def profile_address():
    if request.method == 'POST':
        name = request.form['name']
        phone = request.form['phone']
        address_text = request.form['address_text']
        postal_code = request.form.get('postal_code', '')
        if current_user.address:
            addr = current_user.address
            addr.name, addr.phone, addr.address_text, addr.postal_code = name, phone, address_text, postal_code
        else:
            addr = Address(user_id=current_user.id, name=name, phone=phone, address_text=address_text, postal_code=postal_code)
            db.session.add(addr)
        db.session.commit()
        flash('地址保存成功', 'success')
        return redirect(url_for('frontend.profile_address'))
    return render_template('frontend/address.html', address=current_user.address)


@frontend.route('/orders')
@login_required
@user_required
def orders():
    status_filter = request.args.get('status', 'all')
    orders_query = Order.query.filter_by(user_id=current_user.id)
    if status_filter != 'all':
        orders_query = orders_query.filter_by(status=status_filter)
    orders_list = orders_query.order_by(Order.created_at.desc()).all()
    return render_template('frontend/orders.html', orders=orders_list, current_filter=status_filter)


@frontend.route('/orders/<order_no>/cancel', methods=['POST'])
@login_required
@user_required
def cancel_order(order_no):
    order = Order.query.filter_by(order_no=order_no, user_id=current_user.id).first_or_404()
    if order.status in ['done', 'canceled']:
        flash('该订单当前状态不可取消', 'error')
        return redirect(url_for('frontend.order_detail', order_no=order_no))
    order.status = 'canceled'
    order.canceled_at = datetime.utcnow()
    order.cancel_reason = '用户主动取消'
    restore_order_stock(order)
    db.session.commit()
    flash('订单已取消', 'success')
    return redirect(url_for('frontend.orders'))


@frontend.route('/orders/<order_no>')
@login_required
@user_required
def order_detail(order_no):
    order = Order.query.filter_by(order_no=order_no, user_id=current_user.id).first_or_404()
    alipay_qr = get_setting('alipay_qrcode')
    wechat_qr = get_setting('wechat_qrcode')
    fill_order_items_unit_price(order)
    return render_template(
        'frontend/order_detail.html',
        order=order,
        alipay_qr=alipay_qr,
        wechat_qr=wechat_qr
    )


@frontend.route('/orders/<order_no>/payment-attachments', methods=['POST'])
@login_required
def upload_payment_attachments(order_no):
    order = Order.query.filter_by(order_no=order_no, user_id=current_user.id).first_or_404()
    if 'images' not in request.files:
        flash('请选择付款截图', 'error')
        return redirect(url_for('frontend.order_detail', order_no=order_no))
    files = request.files.getlist('images')
    if len(files) > 3:
        flash('最多只能上传3张图片', 'error')
        return redirect(url_for('frontend.order_detail', order_no=order_no))
    uploaded_files = []
    upload_folder = current_app.config['UPLOAD_FOLDER']
    for file in files:
        if file and file.filename and allowed_file(file.filename):
            filename = secure_filename(file.filename)
            filename = datetime.now().strftime('%Y%m%d_%H%M%S_') + filename
            filepath = os.path.join(upload_folder, 'payments', filename)
            file.save(filepath)
            uploaded_files.append(f'payments/{filename}')
    if uploaded_files:
        attachment = PaymentAttachment(
            order_id=order.id,
            user_note=request.form.get('note', ''),
            image_urls=json.dumps(uploaded_files)
        )
        db.session.add(attachment)
        db.session.commit()
        flash('付款截图上传成功，等待核验', 'success')
    else:
        flash('请上传有效的图片文件', 'error')
    return redirect(url_for('frontend.order_detail', order_no=order_no))
