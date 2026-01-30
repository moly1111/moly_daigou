# 工具函数、装饰器、模板过滤器
import os
import json
import random
import string
from datetime import datetime
from zoneinfo import ZoneInfo
from functools import wraps

from flask import redirect, request, current_app
from flask_login import current_user

from core.extensions import db
from core.models import SystemSettings, AdminUser, User, Product

CN_TZ = ZoneInfo('Asia/Shanghai')
UTC_TZ = ZoneInfo('UTC')


def require_env(key: str, forbidden_values=None) -> str:
    val = os.getenv(key)
    if forbidden_values is None:
        forbidden_values = []
    if val is None or val.strip() == '' or val in forbidden_values:
        raise RuntimeError(f"缺少必要环境变量 {key}，请在 .env 或系统环境中正确设置")
    return val


def get_setting(key, default=None):
    setting = SystemSettings.query.filter_by(key=key).first()
    return setting.value if setting else default


def set_setting(key, value):
    setting = SystemSettings.query.filter_by(key=key).first()
    if setting:
        setting.value = value
    else:
        setting = SystemSettings(key=key, value=value)
        db.session.add(setting)
    db.session.commit()


def allowed_file(filename):
    allowed = {'png', 'jpg', 'jpeg', 'gif', 'webp'}
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in allowed


def generate_order_no():
    timestamp = datetime.now().strftime('%Y%m%d%H%M%S')
    random_suffix = ''.join(random.choices(string.digits, k=6))
    return f"{timestamp}{random_suffix}"


def is_valid_email(email: str) -> bool:
    return isinstance(email, str) and '@' in email and '.' in email


def admin_required(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        if not current_user.is_authenticated:
            return redirect(
                __url_for_admin_login(next=request.path)
            )
        if not isinstance(current_user, AdminUser):
            from flask_login import logout_user
            logout_user()
            return redirect(
                __url_for_admin_login(next=request.path)
            )
        return func(*args, **kwargs)
    return wrapper


def user_required(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        if not current_user.is_authenticated or isinstance(current_user, AdminUser):
            from flask import url_for
            return redirect(url_for('frontend.login'))
        if getattr(current_user, 'is_banned', False):
            from flask_login import logout_user
            from flask import flash, url_for
            logout_user()
            flash('您的账户已被封禁，请联系管理员', 'error')
            return redirect(url_for('frontend.login'))
        return func(*args, **kwargs)
    return wrapper


def __url_for_admin_login(**kwargs):
    from flask import url_for
    return url_for('admin.admin_login', **kwargs)


def fill_order_items_unit_price(order):
    """批量填充订单条目的单价（缺省时从商品计算），避免 N+1 查询。"""
    items_needing = [it for it in order.items if not it.unit_price and it.product_id]
    if not items_needing:
        return
    ids = list({it.product_id for it in items_needing})
    products = Product.query.filter(Product.id.in_(ids)).all()
    pmap = {p.id: p for p in products}
    for it in items_needing:
        p = pmap.get(it.product_id)
        if not p:
            continue
        if it.variant_id and it.variant:
            it.unit_price = it.variant.get_display_price(p)
        else:
            it.unit_price = float(p.price_rmb or 0) + p.get_variant_extra_price(it.variant_name)


def restore_order_stock(order):
    """订单取消时恢复规格库存。"""
    from core.models import ProductVariant
    for it in order.items:
        if it.variant_id and it.qty:
            pv = ProductVariant.query.get(it.variant_id)
            if pv and pv.stock is not None:
                pv.stock = (pv.stock or 0) + it.qty


def product_id_to_title_map(product_ids):
    """批量查询 product_id -> title，返回 dict。空集合返回 {}。"""
    if not product_ids:
        return {}
    ids = list(set(product_ids))
    products = Product.query.filter(Product.id.in_(ids)).all()
    return {p.id: p.title for p in products}


def register_filters(app):
    """注册模板过滤器。"""

    @app.template_filter('from_json')
    def from_json_filter(value):
        if value:
            try:
                return json.loads(value)
            except Exception:
                return []
        return []

    @app.template_filter('cn_time')
    def cn_time(value, fmt='%Y-%m-%d %H:%M'):
        if not value:
            return ''
        try:
            dt = value
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=UTC_TZ)
            return dt.astimezone(CN_TZ).strftime(fmt)
        except Exception:
            try:
                return value.strftime(fmt)
            except Exception:
                return str(value)
