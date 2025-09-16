from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, session
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import os
import json
import csv
import io
import random
import string
from apscheduler.schedulers.background import BackgroundScheduler
import atexit
from dotenv import load_dotenv
from send_email import send_email

# 加载环境变量
load_dotenv()

app = Flask(__name__)
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'your-secret-key-change-in-production')
app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv('DATABASE_URL', 'sqlite:///daigou.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['UPLOAD_FOLDER'] = os.getenv('UPLOAD_FOLDER', 'static/uploads')
# 将全局上传上限提升到 50MB（具体类型限制在各上传入口控制）
app.config['MAX_CONTENT_LENGTH'] = int(os.getenv('MAX_CONTENT_LENGTH', '52428800'))

# 确保上传目录存在
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
os.makedirs(os.path.join(app.config['UPLOAD_FOLDER'], 'products'), exist_ok=True)
os.makedirs(os.path.join(app.config['UPLOAD_FOLDER'], 'payments'), exist_ok=True)
os.makedirs(os.path.join(app.config['UPLOAD_FOLDER'], 'qrcodes'), exist_ok=True)
os.makedirs(os.path.join(app.config['UPLOAD_FOLDER'], 'covers'), exist_ok=True)

db = SQLAlchemy(app)
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

# 数据库模型
class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(128), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    last_login_at = db.Column(db.DateTime)
    
    # 关联
    address = db.relationship('Address', backref='user', uselist=False)
    orders = db.relationship('Order', backref='user', lazy=True)

    # 区分用户与管理员的会话ID，避免冲突
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
    status = db.Column(db.String(10), default='up')  # up/down
    images = db.Column(db.Text)  # JSON string
    note = db.Column(db.String(200))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

class Order(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    order_no = db.Column(db.String(24), unique=True, nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    status = db.Column(db.String(20), default='pending')  # pending/processing/done/canceled
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
    internal_notes = db.Column(db.Text)  # JSON string
    
    # 关联
    items = db.relationship('OrderItem', backref='order', lazy=True)
    payment_attachments = db.relationship('PaymentAttachment', backref='order', lazy=True)

class OrderItem(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    order_id = db.Column(db.Integer, db.ForeignKey('order.id'), nullable=False)
    product_id = db.Column(db.Integer, db.ForeignKey('product.id'), nullable=True)
    name = db.Column(db.String(100), nullable=False)
    spec_note = db.Column(db.String(200))
    qty = db.Column(db.Integer, nullable=False)
    link = db.Column(db.String(500))
    images = db.Column(db.Text)  # JSON string

class CartItem(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    product_id = db.Column(db.Integer, db.ForeignKey('product.id'), nullable=False)
    qty = db.Column(db.Integer, nullable=False, default=1)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class PaymentAttachment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    order_id = db.Column(db.Integer, db.ForeignKey('order.id'), nullable=False)
    user_note = db.Column(db.String(200))
    image_urls = db.Column(db.Text)  # JSON string
    uploaded_at = db.Column(db.DateTime, default=datetime.utcnow)

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

@login_manager.user_loader
def load_user(user_id: str):
    try:
        role, raw_id = user_id.split(":", 1)
        if role == 'admin':
            return AdminUser.query.get(int(raw_id))
        if role == 'user':
            return User.query.get(int(raw_id))
    except Exception:
        pass
    return None

# 模板过滤器
@app.template_filter('from_json')
def from_json_filter(value):
    if value:
        try:
            return json.loads(value)
        except:
            return []
    return []

# 中国时区格式化过滤器
CN_TZ = ZoneInfo('Asia/Shanghai')
UTC_TZ = ZoneInfo('UTC')

@app.template_filter('cn_time')
def cn_time(value, fmt='%Y-%m-%d %H:%M'):
    if not value:
        return ''
    try:
        dt = value
        # 统一视为 UTC，再转换到中国时区
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC_TZ)
        return dt.astimezone(CN_TZ).strftime(fmt)
    except Exception:
        try:
            return value.strftime(fmt)
        except Exception:
            return str(value)

# 工具函数
def allowed_file(filename):
    ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'webp'}
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def generate_order_no():
    timestamp = datetime.now().strftime('%Y%m%d%H%M%S')
    random_suffix = ''.join(random.choices(string.digits, k=6))
    return f"{timestamp}{random_suffix}"

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

def admin_required(func):
    from functools import wraps
    @wraps(func)
    def wrapper(*args, **kwargs):
        if not current_user.is_authenticated:
            # 未登录直接去管理员登录页
            return redirect(url_for('admin_login', next=request.path))
        if not isinstance(current_user, AdminUser):
            # 已登录为普通用户，强制退出并去管理员登录
            logout_user()
            return redirect(url_for('admin_login', next=request.path))
        return func(*args, **kwargs)
    return wrapper

def user_required(func):
    from functools import wraps
    @wraps(func)
    def wrapper(*args, **kwargs):
        if not current_user.is_authenticated or isinstance(current_user, AdminUser):
            return redirect(url_for('login'))
        return func(*args, **kwargs)
    return wrapper

def is_valid_email(email: str) -> bool:
    return isinstance(email, str) and '@' in email and '.' in email

@app.context_processor
def inject_role_helpers():
    def is_admin():
        try:
            from flask_login import AnonymousUserMixin
            if isinstance(current_user, AnonymousUserMixin) or not current_user.is_authenticated:
                return False
            return isinstance(current_user._get_current_object(), AdminUser)
        except Exception:
            return False
    def is_user():
        try:
            from flask_login import AnonymousUserMixin
            if isinstance(current_user, AnonymousUserMixin) or not current_user.is_authenticated:
                return False
            return isinstance(current_user._get_current_object(), User)
        except Exception:
            return False
    # 站点封面
    cover = get_setting('cover_image')
    return dict(is_admin=is_admin, is_user=is_user, current_year=datetime.utcnow().year, site_cover=cover)

# 自动取消未支付订单的任务
def auto_cancel_unpaid_orders():
    with app.app_context():
        auto_cancel_enabled = get_setting('auto_cancel_enabled', 'true')
        if auto_cancel_enabled.lower() != 'true':
            return
        
        cancel_hours = int(get_setting('auto_cancel_hours', '24'))
        cutoff_time = datetime.utcnow() - timedelta(hours=cancel_hours)
        
        unpaid_orders = Order.query.filter(
            Order.status == 'pending',
            Order.is_paid == False,
            Order.created_at < cutoff_time
        ).all()
        
        for order in unpaid_orders:
            order.status = 'canceled'
            order.canceled_at = datetime.utcnow()
            order.cancel_reason = f'超过{cancel_hours}小时未付款自动取消'
        
        if unpaid_orders:
            db.session.commit()
            print(f"自动取消了 {len(unpaid_orders)} 个未支付订单")

def cleanup_expired_verification_codes():
    """清理过期的验证码"""
    with app.app_context():
        try:
            # 删除过期的验证码记录
            expired_count = EmailVerification.query.filter(
                EmailVerification.expire_at < datetime.utcnow()
            ).delete()
            
            if expired_count > 0:
                db.session.commit()
                print(f"清理了 {expired_count} 个过期验证码")
                
        except Exception as e:
            print(f"清理过期验证码时出错: {e}")

# 启动定时任务
scheduler = BackgroundScheduler()
scheduler.add_job(func=auto_cancel_unpaid_orders, trigger="interval", hours=1)
scheduler.add_job(func=cleanup_expired_verification_codes, trigger="interval", hours=6)  # 每6小时清理一次
scheduler.start()
atexit.register(lambda: scheduler.shutdown())

# 路由
@app.route('/')
def index():
    # 上架优先，按更新时间倒序；下架置后
    status_order = db.case((Product.status=='down', 1), else_=0)
    products = Product.query.filter(Product.status.in_(['up','down'])).order_by(status_order.asc(), Product.updated_at.desc()).all()
    return render_template('frontend/index.html', products=products)

@app.route('/cart')
@login_required
@user_required
def cart_page():
    # 下架商品放到最后
    status_order = db.case((Product.status=='down', 1), else_=0)
    items = db.session.query(CartItem, Product)\
        .join(Product, CartItem.product_id==Product.id)\
        .filter(CartItem.user_id==current_user.id)\
        .order_by(status_order.asc(), CartItem.created_at.asc())\
        .all()
    return render_template('frontend/cart.html', cart_items=items)

@app.route('/cart/add/<int:product_id>', methods=['POST'])
@login_required
@user_required
def add_to_cart(product_id: int):
    product = Product.query.get_or_404(product_id)
    if product.status != 'up':
        flash('该商品未上架，无法加入购物车', 'error')
        return redirect(url_for('index'))
    qty = int(request.form.get('qty', '1') or '1')
    qty = max(1, min(qty, 999))
    item = CartItem.query.filter_by(user_id=current_user.id, product_id=product_id).first()
    if item:
        item.qty += qty
    else:
        item = CartItem(user_id=current_user.id, product_id=product_id, qty=qty)
        db.session.add(item)
    db.session.commit()
    flash(f'“{product.title}” ×{qty} 已加入购物车', 'success')
    return redirect(request.referrer or url_for('index'))

@app.route('/cart/update/<int:item_id>', methods=['POST'])
@login_required
@user_required
def update_cart(item_id: int):
    item = CartItem.query.get_or_404(item_id)
    if item.user_id != current_user.id:
        return redirect(url_for('cart_page'))
    qty = int(request.form.get('qty', '1') or '1')
    if qty <= 0:
        db.session.delete(item)
    else:
        item.qty = min(qty, 999)
    db.session.commit()
    return redirect(url_for('cart_page'))

@app.route('/cart/remove/<int:item_id>', methods=['POST'])
@login_required
@user_required
def remove_cart(item_id: int):
    item = CartItem.query.get_or_404(item_id)
    if item.user_id == current_user.id:
        db.session.delete(item)
        db.session.commit()
        flash('已移除', 'success')
    return redirect(url_for('cart_page'))

@app.route('/cart/checkout', methods=['POST'])
@login_required
@user_required
def cart_checkout():
    # 接收选中的购物车条目ID
    ids = request.form.getlist('item_id')
    if not ids:
        flash('请先选择要结算的商品', 'error')
        return redirect(url_for('cart_page'))
    cart_items = db.session.query(CartItem, Product).join(Product, CartItem.product_id==Product.id)\
        .filter(CartItem.user_id==current_user.id, CartItem.id.in_(ids)).all()
    if not cart_items:
        flash('未找到选中的商品', 'error')
        return redirect(url_for('cart_page'))

    # 校验是否有下架商品
    invalid = [(ci, p) for (ci, p) in cart_items if p.status != 'up']
    if invalid:
        names = '、'.join([p.title for (ci, p) in invalid])
        flash(f'以下商品已下架，未能提交订单：{names}。请移除或等待上架。', 'error')
        return redirect(url_for('cart_page'))

    # 计算商品金额
    amount_items = sum([float(p.price_rmb) * ci.qty for (ci, p) in cart_items])
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
        oi = OrderItem(order_id=order.id, product_id=p.id, name=p.title, spec_note=p.note or '', qty=ci.qty)
        db.session.add(oi)
        db.session.delete(ci)
    db.session.commit()
    flash(f'订单已提交，订单号：{order_no}，请前往订单详情查看并付款', 'success')
    return redirect(url_for('order_detail', order_no=order_no))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']
        user = User.query.filter_by(email=email).first()
        
        if user and check_password_hash(user.password_hash, password):
            remember = True
            login_user(user, remember=remember, duration=timedelta(days=7))
            user.last_login_at = datetime.utcnow()
            db.session.commit()
            return redirect(url_for('index'))
        else:
            flash('邮箱或密码错误', 'error')
    
    return render_template('frontend/login.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']
        code = request.form.get('code', '')

        if not is_valid_email(email):
            flash('邮箱格式不正确', 'error')
            return render_template('frontend/register.html')

        if User.query.filter_by(email=email).first():
            flash('该邮箱已被注册', 'error')
            return render_template('frontend/register.html')

        # 校验验证码
        ver = EmailVerification.query.filter_by(email=email, code=code, used=False).order_by(EmailVerification.id.desc()).first()
        if not ver or ver.expire_at < datetime.utcnow():
            flash('验证码无效或已过期', 'error')
            return render_template('frontend/register.html')

        # 标记验证码为已使用
        ver.used = True
        db.session.commit()

        user = User(
            email=email,
            password_hash=generate_password_hash(password)
        )
        db.session.add(user)
        db.session.commit()
        
        # 注册成功后自动登录
        login_user(user, remember=True)
        flash('注册成功，已自动登录', 'success')
        return redirect(url_for('index'))
    
    return render_template('frontend/register.html')

@app.route('/api/auth/send-code', methods=['POST'])
def send_register_code():
    data = request.form if request.form else request.json
    email = (data.get('email') if data else '').strip() if data else ''
    if not is_valid_email(email):
        return jsonify({'code':400, 'message':'邮箱格式不正确', 'data':None}), 400

    # 检查是否已注册
    if User.query.filter_by(email=email).first():
        return jsonify({'code':400, 'message':'该邮箱已被注册', 'data':None}), 400

    # 标记该邮箱的所有旧验证码为已使用
    EmailVerification.query.filter_by(email=email, used=False).update({'used': True})
    
    # 生成6位验证码，10分钟有效
    code = ''.join(random.choices(string.digits, k=6))
    expire_at = datetime.utcnow() + timedelta(minutes=10)
    rec = EmailVerification(email=email, code=code, expire_at=expire_at)
    db.session.add(rec)
    db.session.commit()

    try:
        send_email('注册验证码', f'您的验证码为：{code}，10分钟内有效。', email)
    except Exception as e:
        print('发送验证码失败: ', e)
        return jsonify({'code':500, 'message':'验证码发送失败', 'data':None}), 500

    return jsonify({'code':0, 'message':'验证码已发送', 'data':{'expire_minutes':10}})

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('index'))

@app.route('/profile/address', methods=['GET', 'POST'])
@login_required
@user_required
def profile_address():
    if request.method == 'POST':
        name = request.form['name']
        phone = request.form['phone']
        address_text = request.form['address_text']
        postal_code = request.form.get('postal_code', '')
        
        if current_user.address:
            address = current_user.address
            address.name = name
            address.phone = phone
            address.address_text = address_text
            address.postal_code = postal_code
        else:
            address = Address(
                user_id=current_user.id,
                name=name,
                phone=phone,
                address_text=address_text,
                postal_code=postal_code
            )
            db.session.add(address)
        
        db.session.commit()
        flash('地址保存成功', 'success')
        return redirect(url_for('profile_address'))
    
    return render_template('frontend/address.html', address=current_user.address)

@app.route('/orders')
@login_required
@user_required
def orders():
    status_filter = request.args.get('status', 'all')
    orders_query = Order.query.filter_by(user_id=current_user.id)
    
    if status_filter != 'all':
        orders_query = orders_query.filter_by(status=status_filter)
    
    orders = orders_query.order_by(Order.created_at.desc()).all()
    return render_template('frontend/orders.html', orders=orders, current_filter=status_filter)

@app.route('/orders/<order_no>/cancel', methods=['POST'])
@login_required
@user_required
def cancel_order(order_no):
    order = Order.query.filter_by(order_no=order_no, user_id=current_user.id).first_or_404()
    if order.status in ['done', 'canceled']:
        flash('该订单当前状态不可取消', 'error')
        return redirect(url_for('order_detail', order_no=order_no))
    # 仅允许未付款或处理中未完成时取消
    order.status = 'canceled'
    order.canceled_at = datetime.utcnow()
    order.cancel_reason = '用户主动取消'
    db.session.commit()
    flash('订单已取消', 'success')
    return redirect(url_for('orders'))

@app.route('/orders/<order_no>')
@login_required
@user_required
def order_detail(order_no):
    order = Order.query.filter_by(order_no=order_no, user_id=current_user.id).first_or_404()
    
    # 获取支付二维码设置
    alipay_qr = get_setting('alipay_qrcode')
    wechat_qr = get_setting('wechat_qrcode')
    
    return render_template('frontend/order_detail.html', 
                         order=order, 
                         alipay_qr=alipay_qr, 
                         wechat_qr=wechat_qr)

@app.route('/orders/<order_no>/payment-attachments', methods=['POST'])
@login_required
def upload_payment_attachments(order_no):
    order = Order.query.filter_by(order_no=order_no, user_id=current_user.id).first_or_404()
    
    if 'images' not in request.files:
        flash('请选择付款截图', 'error')
        return redirect(url_for('order_detail', order_no=order_no))
    
    files = request.files.getlist('images')
    if len(files) > 3:
        flash('最多只能上传3张图片', 'error')
        return redirect(url_for('order_detail', order_no=order_no))
    
    uploaded_files = []
    for file in files:
        if file and file.filename and allowed_file(file.filename):
            filename = secure_filename(file.filename)
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S_')
            filename = timestamp + filename
            filepath = os.path.join(app.config['UPLOAD_FOLDER'], 'payments', filename)
            file.save(filepath)
            uploaded_files.append(f'payments/{filename}')
    
    if uploaded_files:
        user_note = request.form.get('note', '')
        attachment = PaymentAttachment(
            order_id=order.id,
            user_note=user_note,
            image_urls=json.dumps(uploaded_files)
        )
        db.session.add(attachment)
        db.session.commit()
        flash('付款截图上传成功，等待核验', 'success')
    else:
        flash('请上传有效的图片文件', 'error')
    
    return redirect(url_for('order_detail', order_no=order_no))

# 后台管理路由
@app.route('/admin/login', methods=['GET', 'POST'])
def admin_login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        admin = AdminUser.query.filter_by(username=username).first()
        
        if admin and check_password_hash(admin.password_hash, password):
            login_user(admin, remember=True, duration=timedelta(days=7))
            return redirect(url_for('admin_dashboard'))
        else:
            flash('用户名或密码错误', 'error')
    
    return render_template('admin/login.html')

@app.route('/admin/logout')
@admin_required
def admin_logout():
    logout_user()
    return redirect(url_for('admin_login'))

@app.route('/admin')
@admin_required
def admin_dashboard():
    
    # 统计信息
    total_orders = Order.query.count()
    pending_orders = Order.query.filter_by(status='pending').count()
    processing_orders = Order.query.filter_by(status='processing').count()
    total_users = User.query.count()
    
    # 获取当前版本信息
    current_version = Version.query.filter_by(is_current=True).first()
    
    return render_template('admin/dashboard.html',
                         total_orders=total_orders,
                         pending_orders=pending_orders,
                         processing_orders=processing_orders,
                         total_users=total_users,
                         current_version=current_version,
                         now=datetime.utcnow())

@app.route('/admin/products')
@admin_required
def admin_products():
    
    status_order = db.case((Product.status=='down', 1), else_=0)
    products = Product.query.order_by(status_order.asc(), Product.updated_at.desc()).all()
    return render_template('admin/products.html', products=products)

# 用户管理
@app.route('/admin/users')
@login_required
@admin_required
def admin_users():
    users = User.query.order_by(User.created_at.desc()).all()
    return render_template('admin/users.html', users=users)

@app.route('/admin/users/<int:user_id>/edit', methods=['GET', 'POST'])
@login_required
@admin_required
def admin_user_edit(user_id: int):
    user = User.query.get_or_404(user_id)
    if request.method == 'POST':
        email = request.form['email'].strip()
        new_password = request.form.get('password', '').strip()
        if not is_valid_email(email):
            flash('邮箱格式不正确', 'error')
            return render_template('admin/user_form.html', user=user)
        exists = User.query.filter(User.email == email, User.id != user.id).first()
        if exists:
            flash('该邮箱已被使用', 'error')
            return render_template('admin/user_form.html', user=user)
        user.email = email
        if new_password:
            user.password_hash = generate_password_hash(new_password)
        db.session.commit()
        flash('用户信息已更新', 'success')
        return redirect(url_for('admin_users'))
    return render_template('admin/user_form.html', user=user)

@app.route('/admin/users/<int:user_id>/edit-address', methods=['POST'])
@login_required
@admin_required
def admin_user_edit_address(user_id: int):
    user = User.query.get_or_404(user_id)
    name = request.form['name']
    phone = request.form['phone']
    address_text = request.form['address_text']
    postal_code = request.form.get('postal_code','')
    if user.address:
        addr = user.address
        addr.name = name
        addr.phone = phone
        addr.address_text = address_text
        addr.postal_code = postal_code
    else:
        addr = Address(user_id=user.id, name=name, phone=phone, address_text=address_text, postal_code=postal_code)
        db.session.add(addr)
    db.session.commit()
    flash('地址已保存', 'success')
    return redirect(url_for('admin_user_edit', user_id=user.id))

@app.route('/admin/users/<int:user_id>/delete', methods=['POST'])
@login_required
@admin_required
def admin_user_delete(user_id: int):
    user = User.query.get_or_404(user_id)
    # 清理关联数据
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
    return redirect(url_for('admin_users'))

@app.route('/admin/products/new', methods=['GET', 'POST'])
@admin_required
def admin_new_product():
    
    if request.method == 'POST':
        title = request.form['title']
        price_rmb = float(request.form['price_rmb'])
        note = request.form.get('note', '')
        status = request.form.get('status', 'up')
        
        # 处理图片上传
        uploaded_images = []
        if 'images' in request.files:
            files = request.files.getlist('images')
            for file in files:
                if file and file.filename and allowed_file(file.filename):
                    filename = secure_filename(file.filename)
                    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S_')
                    filename = timestamp + filename
                    filepath = os.path.join(app.config['UPLOAD_FOLDER'], 'products', filename)
                    file.save(filepath)
                    uploaded_images.append(f'products/{filename}')
        
        product = Product(
            title=title,
            price_rmb=price_rmb,
            note=note,
            status=status,
            images=json.dumps(uploaded_images) if uploaded_images else None
        )
        db.session.add(product)
        db.session.commit()
        
        flash('商品创建成功', 'success')
        return redirect(url_for('admin_products'))
    
    return render_template('admin/product_form.html')

@app.route('/admin/products/<int:product_id>/edit', methods=['GET', 'POST'])
@admin_required
def admin_edit_product(product_id):
    
    product = Product.query.get_or_404(product_id)
    
    if request.method == 'POST':
        # 仅修改上下架状态的快捷操作（列表页表单只提交 status）
        if 'title' not in request.form and 'price_rmb' not in request.form:
            new_status = request.form.get('status')
            if new_status in ['up', 'down']:
                product.status = new_status
                db.session.commit()
                flash('商品状态已更新', 'success')
                return redirect(url_for('admin_products'))
        
        # 正常编辑表单
        product.title = request.form['title']
        product.price_rmb = float(request.form['price_rmb'])
        product.note = request.form.get('note', '')
        product.status = request.form.get('status', 'up')
        
        # 处理图片上传
        if 'images' in request.files:
            files = request.files.getlist('images')
            new_images = []
            for file in files:
                if file and file.filename and allowed_file(file.filename):
                    filename = secure_filename(file.filename)
                    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S_')
                    filename = timestamp + filename
                    filepath = os.path.join(app.config['UPLOAD_FOLDER'], 'products', filename)
                    file.save(filepath)
                    new_images.append(f'products/{filename}')
            
            if new_images:
                existing_images = json.loads(product.images) if product.images else []
                all_images = existing_images + new_images
                product.images = json.dumps(all_images)
        
        db.session.commit()
        flash('商品更新成功', 'success')
        return redirect(url_for('admin_products'))
    
    return render_template('admin/product_form.html', product=product)

@app.route('/admin/orders')
@admin_required
def admin_orders():
    
    # 筛选参数
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
            dt = datetime.strptime(start_date + ' 00:00:00', '%Y-%m-%d %H:%M:%S')
            orders_query = orders_query.filter(Order.created_at >= dt)
        except Exception:
            pass
    if end_date:
        try:
            dt = datetime.strptime(end_date + ' 23:59:59', '%Y-%m-%d %H:%M:%S')
            orders_query = orders_query.filter(Order.created_at <= dt)
        except Exception:
            pass

    if search:
        like = f"%{search}%"
        orders_query = orders_query.join(User).filter(
            db.or_(
                Order.order_no.like(like),
                User.email.like(like),
                Order.cancel_reason.like(like)
            )
        )
    
    orders = orders_query.order_by(Order.created_at.desc()).all()
    return render_template('admin/orders.html', orders=orders, 
                         status_filter=status_filter, paid_filter=paid_filter, search=search,
                         start_date=start_date or '', end_date=end_date or '')

@app.route('/admin/orders/new', methods=['GET', 'POST'])
@admin_required
def admin_new_order():
    
    if request.method == 'POST':
        user_email = request.form['user_email']
        amount_items = float(request.form['amount_items'])
        amount_shipping = float(request.form['amount_shipping'])
        
        # 查找或创建用户
        user = User.query.filter_by(email=user_email).first()
        if not user:
            # 创建新用户
            temp_password = ''.join(random.choices(string.ascii_letters + string.digits, k=8))
            user = User(
                email=user_email,
                password_hash=generate_password_hash(temp_password)
            )
            db.session.add(user)
            db.session.flush()  # 获取用户ID
        
        # 创建订单
        order_no = generate_order_no()
        order = Order(
            order_no=order_no,
            user_id=user.id,
            amount_items=amount_items,
            amount_shipping=amount_shipping,
            amount_due=amount_items + amount_shipping
        )
        db.session.add(order)
        db.session.flush()  # 获取订单ID
        
        # 处理订单明细
        item_names = request.form.getlist('item_name')
        item_specs = request.form.getlist('item_spec')
        item_qtys = request.form.getlist('item_qty')
        
        for i, name in enumerate(item_names):
            if name.strip():
                item = OrderItem(
                    order_id=order.id,
                    name=name.strip(),
                    spec_note=item_specs[i] if i < len(item_specs) else '',
                    qty=int(item_qtys[i]) if i < len(item_qtys) and item_qtys[i] else 1
                )
                db.session.add(item)
        
        db.session.commit()
        flash(f'订单创建成功，订单号：{order_no}', 'success')
        return redirect(url_for('admin_order_detail', order_no=order_no))
    
    products = Product.query.filter_by(status='up').all()
    return render_template('admin/order_form.html', products=products)

@app.route('/admin/orders/<order_no>')
@admin_required
def admin_order_detail(order_no):
    
    order = Order.query.filter_by(order_no=order_no).first_or_404()
    return render_template('admin/order_detail.html', order=order)

@app.route('/admin/orders/<order_no>/mark-paid', methods=['POST'])
@admin_required
def admin_mark_paid(order_no):
    
    order = Order.query.filter_by(order_no=order_no).first_or_404()
    order.is_paid = True
    order.paid_at = datetime.utcnow()
    order.status = 'processing'
    db.session.commit()
    
    # 发送邮件通知
    try:
        subject = f"订单 {order_no} 付款确认"
        message = f"""
亲爱的 {order.user.email}，

您的订单 {order_no} 付款已确认，订单状态已更新为"处理中"。

订单详情：
- 订单号：{order_no}
- 商品金额：¥{order.amount_items}
- 运费：¥{order.amount_shipping}
- 合计：¥{order.amount_due}
- 状态：处理中

我们将尽快为您处理订单，请保持手机畅通。

感谢您的信任！
        """
        send_email(subject, message, order.user.email)
    except Exception as e:
        print(f"邮件发送失败: {e}")
    
    flash('订单已标记为已付款', 'success')
    return redirect(url_for('admin_order_detail', order_no=order_no))

@app.route('/admin/orders/<order_no>/mark-unpaid', methods=['POST'])
@admin_required
def admin_mark_unpaid(order_no):
    
    order = Order.query.filter_by(order_no=order_no).first_or_404()
    order.is_paid = False
    order.paid_at = None
    order.status = 'pending'
    db.session.commit()
    
    flash('订单已标记为未付款', 'success')
    return redirect(url_for('admin_order_detail', order_no=order_no))

@app.route('/admin/orders/<order_no>/status', methods=['POST'])
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
    
    db.session.commit()
    
    # 发送邮件通知
    try:
        status_names = {
            'pending': '待支付',
            'processing': '处理中',
            'done': '已完成',
            'canceled': '已取消'
        }
        
        subject = f"订单 {order_no} 状态更新"
        message = f"""
亲爱的 {order.user.email}，

您的订单 {order_no} 状态已更新。

订单详情：
- 订单号：{order_no}
- 原状态：{status_names.get(old_status, old_status)}
- 新状态：{status_names.get(new_status, new_status)}
- 商品金额：¥{order.amount_items}
- 运费：¥{order.amount_shipping}
- 合计：¥{order.amount_due}
"""
        
        if new_status == 'done':
            message += "\n订单已完成，感谢您的购买！"
        elif new_status == 'canceled':
            message += f"\n取消原因：{reason}"
        
        message += "\n\n如有疑问，请联系我们。"
        
        send_email(subject, message, order.user.email)
    except Exception as e:
        print(f"邮件发送失败: {e}")
    
    flash(f'订单状态已更新为：{new_status}', 'success')
    return redirect(url_for('admin_order_detail', order_no=order_no))

@app.route('/admin/purchase-list', methods=['GET'])
@admin_required
def admin_purchase_preview():
    # 筛选参数
    start_date = request.args.get('start_date')
    end_date = request.args.get('end_date')
    keyword = request.args.get('q', '')

    orders_q = Order.query.filter_by(status='processing', is_paid=True)
    if start_date:
        try:
            dt = datetime.strptime(start_date + ' 00:00:00', '%Y-%m-%d %H:%M:%S')
            orders_q = orders_q.filter(Order.created_at >= dt)
        except Exception:
            pass
    if end_date:
        try:
            dt = datetime.strptime(end_date + ' 23:59:59', '%Y-%m-%d %H:%M:%S')
            orders_q = orders_q.filter(Order.created_at <= dt)
        except Exception:
            pass
    if keyword:
        like = f"%{keyword}%"
        orders_q = orders_q.join(User).filter(db.or_(Order.order_no.like(like), User.email.like(like)))

    orders = orders_q.order_by(Order.created_at.asc()).all()

    # 展平到条目层
    rows = []
    for order in orders:
        user = order.user
        addr = user.address
        for item in order.items:
            rows.append({
                'order_no': order.order_no,
                'created_at': order.created_at,
                'email': user.email,
                'receiver': addr.name if addr else '',
                'phone': addr.phone if addr else '',
                'address': addr.address_text if addr else '',
                'name': item.name,
                'spec': item.spec_note or '',
                'qty': item.qty,
                'source': '商品库' if item.product_id else '自定义'
            })

    return render_template('admin/purchase_preview.html', rows=rows, start_date=start_date or '', end_date=end_date or '', keyword=keyword)

@app.route('/admin/purchase-list/download', methods=['GET'])
@admin_required
def admin_purchase_download():
    start_date = request.args.get('start_date')
    end_date = request.args.get('end_date')
    keyword = request.args.get('q', '')

    orders_q = Order.query.filter_by(status='processing', is_paid=True)
    if start_date:
        try:
            dt = datetime.strptime(start_date + ' 00:00:00', '%Y-%m-%d %H:%M:%S')
            orders_q = orders_q.filter(Order.created_at >= dt)
        except Exception:
            pass
    if end_date:
        try:
            dt = datetime.strptime(end_date + ' 23:59:59', '%Y-%m-%d %H:%M:%S')
            orders_q = orders_q.filter(Order.created_at <= dt)
        except Exception:
            pass
    if keyword:
        like = f"%{keyword}%"
        orders_q = orders_q.join(User).filter(db.or_(Order.order_no.like(like), User.email.like(like)))

    orders = orders_q.order_by(Order.created_at.asc()).all()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['订单号','下单时间','用户邮箱','收货人','手机号','地址','商品名称','规格备注','数量','商品来源','商品链接','备注'])
    for order in orders:
        user = order.user
        addr = user.address
        receiver = addr.name if addr else ''
        phone = addr.phone if addr else ''
        addr_text = addr.address_text if addr else ''
        for item in order.items:
            writer.writerow([
                order.order_no,
                order.created_at.strftime('%Y-%m-%d %H:%M:%S'),
                user.email,
                receiver,
                phone,
                addr_text,
                item.name,
                item.spec_note or '',
                item.qty,
                ('商品库' if item.product_id else '自定义'),
                '',
                ''
            ])
    output.seek(0)

    # 动态文件名：日期范围 + 关键字
    parts = []
    today = datetime.utcnow().strftime('%Y%m%d')
    parts.append(today)
    if start_date or end_date:
        parts.append(f"{start_date or 'begin'}-to-{end_date or 'end'}")
    if keyword:
        parts.append(f"q-{keyword}")
    filename = 'purchase_' + '_'.join(parts) + '.csv'

    response = app.response_class(
        output.getvalue(),
        mimetype='text/csv',
        headers={'Content-Disposition': f'attachment; filename={filename}'}
    )
    return response

@app.route('/admin/settings')
@admin_required
def admin_settings():
    
    alipay_qr = get_setting('alipay_qrcode')
    wechat_qr = get_setting('wechat_qrcode')
    auto_cancel_enabled = get_setting('auto_cancel_enabled', 'true')
    auto_cancel_hours = get_setting('auto_cancel_hours', '24')
    
    return render_template('admin/settings.html',
                         alipay_qr=alipay_qr,
                         wechat_qr=wechat_qr,
                         auto_cancel_enabled=auto_cancel_enabled,
                         auto_cancel_hours=auto_cancel_hours)

@app.route('/admin/settings/cover', methods=['POST'])
@admin_required
def admin_update_cover():
    if 'cover' in request.files:
        file = request.files['cover']
        if file and file.filename and allowed_file(file.filename):
            filename = secure_filename(file.filename)
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S_')
            filename = timestamp + filename
            filepath = os.path.join(app.config['UPLOAD_FOLDER'], 'covers', filename)
            file.save(filepath)
            set_setting('cover_image', f'covers/{filename}')
            flash('封面已更新', 'success')
        else:
            flash('请选择有效的图片文件', 'error')
    else:
        flash('未选择文件', 'error')
    return redirect(url_for('admin_settings'))

@app.route('/admin/settings/payment-qrcodes', methods=['POST'])
@admin_required
def admin_update_qrcodes():
    
    # 处理支付宝二维码
    if 'alipay_qr' in request.files:
        file = request.files['alipay_qr']
        if file and file.filename and allowed_file(file.filename):
            filename = secure_filename(file.filename)
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S_')
            filename = timestamp + filename
            filepath = os.path.join(app.config['UPLOAD_FOLDER'], 'qrcodes', filename)
            file.save(filepath)
            set_setting('alipay_qrcode', f'qrcodes/{filename}')
    
    # 处理微信二维码
    if 'wechat_qr' in request.files:
        file = request.files['wechat_qr']
        if file and file.filename and allowed_file(file.filename):
            filename = secure_filename(file.filename)
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S_')
            filename = timestamp + filename
            filepath = os.path.join(app.config['UPLOAD_FOLDER'], 'qrcodes', filename)
            file.save(filepath)
            set_setting('wechat_qrcode', f'qrcodes/{filename}')
    
    flash('收款二维码更新成功', 'success')
    return redirect(url_for('admin_settings'))

@app.route('/admin/settings/order-rules', methods=['POST'])
@admin_required
def admin_update_order_rules():
    
    auto_cancel_enabled = request.form.get('auto_cancel_enabled', 'false')
    auto_cancel_hours = request.form.get('auto_cancel_hours', '24')
    
    set_setting('auto_cancel_enabled', auto_cancel_enabled)
    set_setting('auto_cancel_hours', auto_cancel_hours)
    
    flash('订单规则更新成功', 'success')
    return redirect(url_for('admin_settings'))

# 版本管理路由
@app.route('/admin/versions')
@admin_required
def admin_versions():
    versions = Version.query.order_by(Version.release_date.desc()).all()
    return render_template('admin/versions.html', versions=versions)

@app.route('/admin/versions/new', methods=['GET', 'POST'])
@admin_required
def admin_new_version():
    if request.method == 'POST':
        version = request.form['version']
        title = request.form['title']
        description = request.form['description']
        
        # 检查版本号是否已存在
        if Version.query.filter_by(version=version).first():
            flash('该版本号已存在', 'error')
            return render_template('admin/version_form.html')
        
        # 如果设置为当前版本，先将其他版本设为非当前
        is_current = 'is_current' in request.form
        if is_current:
            Version.query.update({'is_current': False})
        
        new_version = Version(
            version=version,
            title=title,
            description=description,
            is_current=is_current
        )
        
        db.session.add(new_version)
        db.session.commit()
        
        flash('版本信息添加成功', 'success')
        return redirect(url_for('admin_versions'))
    
    return render_template('admin/version_form.html')

@app.route('/admin/versions/<int:version_id>/set-current')
@admin_required
def admin_set_current_version(version_id):
    version = Version.query.get_or_404(version_id)
    
    # 将所有版本设为非当前
    Version.query.update({'is_current': False})
    
    # 设置当前版本
    version.is_current = True
    db.session.commit()
    
    flash(f'已将版本 {version.version} 设为当前版本', 'success')
    return redirect(url_for('admin_versions'))

@app.route('/admin/versions/<int:version_id>/delete')
@admin_required
def admin_delete_version(version_id):
    version = Version.query.get_or_404(version_id)
    
    if version.is_current:
        flash('不能删除当前版本', 'error')
        return redirect(url_for('admin_versions'))
    
    db.session.delete(version)
    db.session.commit()
    
    flash('版本信息删除成功', 'success')
    return redirect(url_for('admin_versions'))

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
        
        # 创建或更新默认管理员账户
        admin_username = os.getenv('ADMIN_USERNAME', 'Moly_Love_you')
        admin_password = os.getenv('ADMIN_PASSWORD', 'MolySoCute!!889150')
        
        admin = AdminUser.query.filter_by(username=admin_username).first()
        if not admin:
            admin = AdminUser(
                username=admin_username,
                password_hash=generate_password_hash(admin_password)
            )
            db.session.add(admin)
            db.session.commit()
            print(f"管理员账户已创建：用户名 {admin_username}，密码已设置")
        else:
            # 确保密码为指定值
            admin.password_hash = generate_password_hash(admin_password)
            db.session.commit()
            print(f"管理员密码已更新：用户名 {admin_username}")
        
        # 创建初始版本1.01
        if not Version.query.filter_by(version='1.01').first():
            initial_version = Version(
                version='1.01',
                title='Moly代购网站 v1.01 - 完整功能版本',
                description='''## 主要功能
- ✅ 用户注册登录系统（邮箱验证码）
- ✅ 商品管理（上架/下架/多图上传）
- ✅ 购物车功能（添加/移除/结算）
- ✅ 订单管理（创建/支付/状态跟踪）
- ✅ 付款截图上传与验证
- ✅ 采购清单导出
- ✅ 用户地址管理
- ✅ 管理员后台
- ✅ 自动取消未支付订单
- ✅ 深浅主题切换
- ✅ 图片放大查看
- ✅ 封面图片设置
- ✅ 版本管理系统

## 技术特性
- Flask + SQLAlchemy + Bootstrap 5
- 环境变量配置
- 跨平台兼容（Windows/Linux）
- 响应式设计
- 安全验证码系统''',
                is_current=True
            )
            db.session.add(initial_version)
            db.session.commit()
            print("初始版本1.01已创建")
        
        # 创建版本1.02（如果不存在）
        if not Version.query.filter_by(version='1.02').first():
            version_102 = Version(
                version='1.02',
                title='Moly代购网站 v1.02 - 用户体验优化',
                description='''## 用户体验优化
- ✅ 新增密码显示/隐藏功能
- ✅ 注册后自动登录，无需重新输入
- ✅ 优化登录和注册流程

## 功能改进
- 🔧 登录页面添加密码可见性切换按钮
- 🔧 注册页面添加密码可见性切换按钮
- 🔧 注册成功后自动登录并跳转到主页
- 🔧 提升用户注册体验

## 技术更新
- 📦 优化前端交互体验
- 📦 改进用户流程设计
- 📦 增强密码输入安全性''',
                is_current=False
            )
            db.session.add(version_102)
            db.session.commit()
            print("版本1.02已创建")
    
    app.run(debug=True, host='0.0.0.0', port=5000)
