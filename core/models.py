# 数据库模型
from datetime import datetime
from flask_login import UserMixin

from core.extensions import db


def _parse_json(value, default=None):
    """解析 JSON 字符串，失败返回 default（默认 []）。"""
    if default is None:
        default = []
    if not value:
        return default
    try:
        import json
        return json.loads(value)
    except Exception:
        return default


class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(120), unique=True, nullable=False)
    username = db.Column(db.String(50), unique=True, nullable=True)
    password_hash = db.Column(db.String(128), nullable=False)
    notes = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    last_login_at = db.Column(db.DateTime)
    is_banned = db.Column(db.Boolean, default=False)

    address = db.relationship('Address', backref='user', uselist=False)
    orders = db.relationship('Order', backref='user', lazy=True)

    def get_id(self):  # type: ignore[override]
        return f"user:{self.id}"


class Address(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    name = db.Column(db.String(30), nullable=False)
    phone = db.Column(db.String(20), nullable=False)
    address_text = db.Column(db.String(200), nullable=False)
    postal_code = db.Column(db.String(10))
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class Product(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(60), nullable=False)
    price_rmb = db.Column(db.Numeric(10, 2), nullable=False)
    cost_price_rmb = db.Column(db.Numeric(10, 2), default=0)
    status = db.Column(db.String(10), default='up')
    images = db.Column(db.Text)
    note = db.Column(db.String(200))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    pinned = db.Column(db.Boolean, default=False)

    product_variants = db.relationship(
        'ProductVariant', backref='product', lazy='joined',
        order_by='ProductVariant.sort_order', cascade='all, delete-orphan'
    )

    @property
    def images_list(self):
        return _parse_json(self.images, [])

    @property
    def variants_list(self):
        """从规格表返回列表，供模板与 API 使用。"""
        return [
            {
                'id': v.id,
                'local_id': getattr(v, 'local_id', None) or (i + 1),
                'name': v.name,
                'price': float(getattr(v, 'price', None) or self.price_rmb or 0),
                'cost': float(getattr(v, 'cost', None) or self.cost_price_rmb or 0),
                'image': v.image,
                'stock': getattr(v, 'stock', 0),
            }
            for i, v in enumerate(sorted(self.product_variants, key=lambda x: (x.sort_order, x.id)))
        ]

    def get_min_display_price(self):
        """最低展示价。"""
        vlist = self.variants_list
        if not vlist:
            return float(self.price_rmb or 0)
        try:
            return min(float(v.get('price') or self.price_rmb or 0) for v in vlist)
        except (TypeError, ValueError):
            return float(self.price_rmb or 0)

    def get_variant_price(self, variant_name):
        """根据规格名返回展示价，无则商品底价。"""
        if not variant_name:
            return float(self.price_rmb or 0)
        for v in self.product_variants or []:
            if v.name == variant_name:
                return float(getattr(v, 'price', None) or self.price_rmb or 0)
        return float(self.price_rmb or 0)

    def get_variant_cost(self, variant_name):
        """根据规格名返回购入价，无则商品最低成本。"""
        if not variant_name:
            return float(self.cost_price_rmb or 0)
        for v in self.product_variants or []:
            if v.name == variant_name:
                return float(getattr(v, 'cost', None) or self.cost_price_rmb or 0)
        return float(self.cost_price_rmb or 0)

    def get_variant_by_id(self, variant_id):
        """根据规格全局 id 返回 ProductVariant，无则 None。"""
        if not variant_id:
            return None
        for v in self.product_variants or []:
            if v.id == variant_id:
                return v
        return None

    def get_variant_by_local_id(self, local_id):
        """根据该商品下的逻辑规格编号（1, 2, 3...）返回 ProductVariant，无则 None。"""
        if local_id is None:
            return None
        for v in self.product_variants or []:
            if getattr(v, 'local_id', None) == local_id:
                return v
        return None


class ProductVariant(db.Model):
    """商品规格表：每个规格一行，直接存展示价与购入价。"""
    __tablename__ = 'product_variant'
    id = db.Column(db.Integer, primary_key=True)
    product_id = db.Column(db.Integer, db.ForeignKey('product.id', ondelete='CASCADE'), nullable=False)
    local_id = db.Column(db.Integer, nullable=False, default=1)  # 该商品下的规格逻辑编号：1, 2, 3...
    name = db.Column(db.String(100), nullable=False)
    price = db.Column(db.Numeric(10, 2), nullable=False, default=0)   # 对外展示价
    cost = db.Column(db.Numeric(10, 2), nullable=False, default=0)    # 采购/购入价
    image = db.Column(db.String(512))
    sort_order = db.Column(db.Integer, default=0)
    stock = db.Column(db.Integer, default=0)

    __table_args__ = (db.UniqueConstraint('product_id', 'local_id', name='uq_product_variant_product_local'),)

    def get_display_price(self, product=None):
        """展示价（直接存储）。"""
        return float(self.price or 0)

    def get_cost(self):
        """购入价（直接存储）。"""
        return float(self.cost or 0)


class Order(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    order_no = db.Column(db.String(24), unique=True, nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    status = db.Column(db.String(20), default='pending')
    amount_items = db.Column(db.Numeric(10, 2), nullable=False)
    amount_shipping = db.Column(db.Numeric(10, 2), nullable=False)
    amount_due = db.Column(db.Numeric(10, 2), nullable=False)
    amount_paid = db.Column(db.Numeric(10, 2), default=0)
    is_paid = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    paid_at = db.Column(db.DateTime)
    completed_at = db.Column(db.DateTime)
    canceled_at = db.Column(db.DateTime)
    cancel_reason = db.Column(db.String(200))
    internal_notes = db.Column(db.Text)
    tracking_number = db.Column(db.String(100))
    shipped_at = db.Column(db.DateTime)

    items = db.relationship('OrderItem', backref='order', lazy=True)
    payment_attachments = db.relationship('PaymentAttachment', backref='order', lazy=True)


class OrderItem(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    order_id = db.Column(db.Integer, db.ForeignKey('order.id'), nullable=False)
    product_id = db.Column(db.Integer, db.ForeignKey('product.id'), nullable=True)
    variant_id = db.Column(db.Integer, db.ForeignKey('product_variant.id'), nullable=True)
    name = db.Column(db.String(100), nullable=False)
    spec_note = db.Column(db.String(200))
    qty = db.Column(db.Integer, nullable=False)
    link = db.Column(db.String(500))
    images = db.Column(db.Text)
    variant_name = db.Column(db.String(100))
    unit_price = db.Column(db.Numeric(10, 2))
    unit_cost = db.Column(db.Numeric(10, 2))

    variant = db.relationship('ProductVariant', backref='order_items', foreign_keys=[variant_id])


class CartItem(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    product_id = db.Column(db.Integer, db.ForeignKey('product.id'), nullable=False)
    variant_id = db.Column(db.Integer, db.ForeignKey('product_variant.id'), nullable=True)
    qty = db.Column(db.Integer, nullable=False, default=1)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    variant_name = db.Column(db.String(100))  # 展示用

    variant = db.relationship('ProductVariant', backref='cart_items', foreign_keys=[variant_id])


class PaymentAttachment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    order_id = db.Column(db.Integer, db.ForeignKey('order.id'), nullable=False)
    user_note = db.Column(db.String(200))
    image_urls = db.Column(db.Text)
    uploaded_at = db.Column(db.DateTime, default=datetime.utcnow)

    @property
    def image_urls_list(self):
        return _parse_json(self.image_urls, [])


class AdminUser(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(128), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def get_id(self):  # type: ignore[override]
        return f"admin:{self.id}"


class SystemSettings(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    key = db.Column(db.String(50), unique=True, nullable=False)
    value = db.Column(db.Text)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class EmailVerification(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(120), index=True, nullable=False)
    code = db.Column(db.String(6), nullable=False)
    expire_at = db.Column(db.DateTime, nullable=False)
    used = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class Version(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    version = db.Column(db.String(20), nullable=False, unique=True)
    title = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text, nullable=False)
    release_date = db.Column(db.DateTime, default=datetime.utcnow)
    is_current = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class ChatMessage(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    sender = db.Column(db.String(10), nullable=False)
    text = db.Column(db.Text)
    image_path = db.Column(db.String(512))
    file_path = db.Column(db.String(512))
    file_name = db.Column(db.String(255))
    file_mime = db.Column(db.String(100))
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    is_read_by_user = db.Column(db.Boolean, default=False)
    is_read_by_admin = db.Column(db.Boolean, default=False)

    user = db.relationship('User', backref=db.backref('chat_messages', lazy='dynamic'))
