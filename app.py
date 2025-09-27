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
from sqlalchemy import func
import atexit
from dotenv import load_dotenv
from send_email import send_email

# 加载环境变量
load_dotenv()

# 强制校验关键环境变量，防止使用默认占位值导致安全风险
def _require_env(key: str, forbidden_values=None) -> str:
    val = os.getenv(key)
    if forbidden_values is None:
        forbidden_values = []
    if val is None or val.strip() == '' or val in forbidden_values:
        raise RuntimeError(f"缺少必要环境变量 {key}，请在 .env 或系统环境中正确设置")
    return val

app = Flask(__name__)

# 强制从环境变量注入 SECRET_KEY（不允许使用默认占位）
_SECRET_KEY = _require_env('SECRET_KEY', forbidden_values=['your-secret-key-change-in-production'])
app.config['SECRET_KEY'] = _SECRET_KEY

# 数据库URL可默认使用本地SQLite，个人部署更便捷；如提供则使用环境变量
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
os.makedirs(os.path.join(app.config['UPLOAD_FOLDER'], 'chat'), exist_ok=True)

db = SQLAlchemy(app)
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

# 数据库模型
class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(120), unique=True, nullable=False)
    username = db.Column(db.String(50), unique=True, nullable=True)  # 用户名，可为空
    password_hash = db.Column(db.String(128), nullable=False)
    notes = db.Column(db.Text)  # 管理员备注
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    last_login_at = db.Column(db.DateTime)
    is_banned = db.Column(db.Boolean, default=False)  # 用户封禁状态
    
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
    cost_price_rmb = db.Column(db.Numeric(10, 2), default=0)
    status = db.Column(db.String(10), default='up')  # up/down
    images = db.Column(db.Text)  # JSON string
    note = db.Column(db.String(200))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    pinned = db.Column(db.Boolean, default=False)
    # 规格：存储为JSON数组 [{"name":"30袋","extra_price":0},{"name":"礼盒","extra_price":20}]
    variants = db.Column(db.Text)  # JSON string: [{name, extra_price, image?}]

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
    variant_name = db.Column(db.String(100))
    # 下单时单价/单成本（历史留痕，避免后续改价影响历史订单）
    unit_price = db.Column(db.Numeric(10, 2))
    unit_cost = db.Column(db.Numeric(10, 2))

class CartItem(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    product_id = db.Column(db.Integer, db.ForeignKey('product.id'), nullable=False)
    qty = db.Column(db.Integer, nullable=False, default=1)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    variant_name = db.Column(db.String(100))

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

# 聊天消息
class ChatMessage(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    sender = db.Column(db.String(10), nullable=False)  # 'user' or 'admin'
    text = db.Column(db.Text)
    image_path = db.Column(db.String(512))
    file_path = db.Column(db.String(512))
    file_name = db.Column(db.String(255))
    file_mime = db.Column(db.String(100))
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    is_read_by_user = db.Column(db.Boolean, default=False)
    is_read_by_admin = db.Column(db.Boolean, default=False)

    user = db.relationship('User', backref=db.backref('chat_messages', lazy='dynamic'))

# =========================
# 聊天相关路由与API
# =========================
def _save_chat_image(file_storage):
    if not file_storage or file_storage.filename == '':
        return None
    filename = secure_filename(file_storage.filename)
    ext = filename.rsplit('.', 1)[-1].lower() if '.' in filename else 'jpg'
    ts = datetime.now().strftime('%Y%m%d_%H%M%S')
    rnd = ''.join(random.choices(string.ascii_letters + string.digits, k=8))
    final_name = f"{ts}_{rnd}.{ext}"
    save_dir = os.path.join(app.config['UPLOAD_FOLDER'], 'chat')
    os.makedirs(save_dir, exist_ok=True)
    path = os.path.join(save_dir, final_name)
    file_storage.save(path)
    return f"/static/uploads/chat/{final_name}"

def _save_chat_file(file_storage):
    if not file_storage or file_storage.filename == '':
        return None, None, None
    filename = secure_filename(file_storage.filename)
    ts = datetime.now().strftime('%Y%m%d_%H%M%S')
    rnd = ''.join(random.choices(string.ascii_letters + string.digits, k=8))
    # 若无扩展名，则基于 mimetype 追加常见扩展名
    mime = file_storage.mimetype or ''
    has_ext = ('.' in filename and not filename.endswith('.'))
    if not has_ext:
        ext_map = {
            'application/pdf': 'pdf',
            'text/plain': 'txt',
            'text/csv': 'csv',
            'application/vnd.openxmlformats-officedocument.wordprocessingml.document': 'docx',
            'application/msword': 'doc',
            'application/vnd.ms-excel': 'xls',
            'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet': 'xlsx',
        }
        guessed = ext_map.get(mime, None)
        if guessed:
            filename = f"{filename}.{guessed}"
    final_name = f"{ts}_{rnd}_{filename}"
    save_dir = os.path.join(app.config['UPLOAD_FOLDER'], 'chat')
    os.makedirs(save_dir, exist_ok=True)
    path = os.path.join(save_dir, final_name)
    file_storage.save(path)
    # 返回URL、原始文件名、mime
    mime = file_storage.mimetype
    return f"/static/uploads/chat/{final_name}", filename, mime

@app.route('/chat', methods=['GET', 'POST'])
@login_required
def chat_page():
    # 仅普通用户可访问
    if isinstance(current_user, AdminUser):
        return redirect(url_for('admin_chats'))
    if request.method == 'POST':
        text = request.form.get('text', '').strip()
        image = request.files.get('image')
        file_any = request.files.get('file')
        image_path = _save_chat_image(image) if image else None
        file_url, file_name, file_mime = _save_chat_file(file_any) if file_any else (None, None, None)
        if not text and not image_path and not file_url:
            flash('请输入消息或选择图片', 'warning')
        else:
            msg = ChatMessage(user_id=current_user.id, sender='user', text=text or None, image_path=image_path, file_path=file_url, file_name=file_name, file_mime=file_mime)
            db.session.add(msg)
            db.session.commit()
        return redirect(url_for('chat_page'))
    # 拉取最近100条
    messages = ChatMessage.query.filter_by(user_id=current_user.id).order_by(ChatMessage.created_at.asc()).limit(100).all()
    # 将发给用户且未读的标记为已读
    ChatMessage.query.filter_by(user_id=current_user.id, sender='admin', is_read_by_user=False).update({ChatMessage.is_read_by_user: True})
    db.session.commit()
    return render_template('frontend/chat.html', messages=messages)

@app.post('/api/chat/send')
@login_required
def api_chat_send_user():
    if isinstance(current_user, AdminUser):
        return jsonify({'error': 'forbidden'}), 403
    text = request.form.get('text', '').strip()
    image = request.files.get('image')
    file_any = request.files.get('file')
    image_path = _save_chat_image(image) if image else None
    file_url, file_name, file_mime = _save_chat_file(file_any) if file_any else (None, None, None)
    if not text and not image_path and not file_url:
        return jsonify({'error': 'empty'}), 400
    msg = ChatMessage(user_id=current_user.id, sender='user', text=text or None, image_path=image_path, file_path=file_url, file_name=file_name, file_mime=file_mime)
    db.session.add(msg)
    db.session.commit()
    return jsonify({
        'id': msg.id,
        'sender': msg.sender,
        'text': msg.text,
        'image_path': msg.image_path,
        'created_at': msg.created_at.isoformat(),
        'file_path': msg.file_path,
        'file_name': msg.file_name,
        'file_mime': msg.file_mime
    })

@app.get('/api/chat/messages')
@login_required
def api_chat_messages_user():
    # 用户端拉取自己的消息，支持基于 since_id 增量获取
    if isinstance(current_user, AdminUser):
        return jsonify({'error': 'forbidden'}), 403
    try:
        since_id = request.args.get('since_id', type=int)
        q = ChatMessage.query.filter_by(user_id=current_user.id).order_by(ChatMessage.id.asc())
        if since_id:
            q = q.filter(ChatMessage.id > since_id)
        msgs = q.all()
        # 将管理员发给用户的未读标记为已读
        ChatMessage.query.filter_by(user_id=current_user.id, sender='admin', is_read_by_user=False).update({ChatMessage.is_read_by_user: True})
        db.session.commit()
        return jsonify([
            {
                'id': m.id,
                'sender': m.sender,
                'text': m.text,
                'image_path': m.image_path,
                'file_path': m.file_path,
                'file_name': m.file_name,
                'file_mime': m.file_mime,
                'created_at': m.created_at.isoformat()
            } for m in msgs
        ])
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/admin/chats')
@login_required
def admin_chats():
    if not isinstance(current_user, AdminUser):
        return redirect(url_for('login'))
    # 汇总每个用户的最后一条消息与未读数
    users = User.query.all()
    data = []
    for u in users:
        last_msg = ChatMessage.query.filter_by(user_id=u.id).order_by(ChatMessage.created_at.desc()).first()
        unread = ChatMessage.query.filter_by(user_id=u.id, sender='user', is_read_by_admin=False).count()
        if last_msg or unread:
            data.append({'user': u, 'last_msg': last_msg, 'unread': unread})
    # 最近活跃优先
    data.sort(key=lambda x: (x['last_msg'].created_at if x['last_msg'] else datetime.min), reverse=True)
    return render_template('admin/chats.html', items=data)

@app.route('/admin/chats/<int:user_id>', methods=['GET', 'POST'])
@login_required
def admin_chat_detail(user_id: int):
    if not isinstance(current_user, AdminUser):
        return redirect(url_for('login'))
    user = User.query.get_or_404(user_id)
    if request.method == 'POST':
        text = request.form.get('text', '').strip()
        image = request.files.get('image')
        image_path = _save_chat_image(image) if image else None
        if not text and not image_path:
            flash('请输入消息或选择图片', 'warning')
        else:
            msg = ChatMessage(user_id=user.id, sender='admin', text=text or None, image_path=image_path)
            db.session.add(msg)
            db.session.commit()
        return redirect(url_for('admin_chat_detail', user_id=user.id))
    messages = ChatMessage.query.filter_by(user_id=user.id).order_by(ChatMessage.created_at.asc()).all()
    # 用户消息标记为已读
    ChatMessage.query.filter_by(user_id=user.id, sender='user', is_read_by_admin=False).update({ChatMessage.is_read_by_admin: True})
    db.session.commit()
    return render_template('admin/chat_detail.html', user=user, messages=messages)

@app.post('/api/admin/chats/<int:user_id>/send')
@login_required
def api_chat_send_admin(user_id: int):
    if not isinstance(current_user, AdminUser):
        return jsonify({'error': 'forbidden'}), 403
    user = User.query.get_or_404(user_id)
    text = request.form.get('text', '').strip()
    image = request.files.get('image')
    file_any = request.files.get('file')
    image_path = _save_chat_image(image) if image else None
    file_url, file_name, file_mime = _save_chat_file(file_any) if file_any else (None, None, None)
    if not text and not image_path and not file_url:
        return jsonify({'error': 'empty'}), 400
    msg = ChatMessage(user_id=user.id, sender='admin', text=text or None, image_path=image_path, file_path=file_url, file_name=file_name, file_mime=file_mime)
    db.session.add(msg)
    db.session.commit()
    return jsonify({
        'id': msg.id,
        'sender': msg.sender,
        'text': msg.text,
        'image_path': msg.image_path,
        'created_at': msg.created_at.isoformat(),
        'file_path': msg.file_path,
        'file_name': msg.file_name,
        'file_mime': msg.file_mime
    })

@app.get('/api/admin/chats/<int:user_id>/messages')
@login_required
def api_chat_messages_admin(user_id: int):
    if not isinstance(current_user, AdminUser):
        return jsonify({'error': 'forbidden'}), 403
    try:
        since_id = request.args.get('since_id', type=int)
        q = ChatMessage.query.filter_by(user_id=user_id).order_by(ChatMessage.id.asc())
        if since_id:
            q = q.filter(ChatMessage.id > since_id)
        msgs = q.all()
        # 将用户发给管理员的未读标记为已读
        ChatMessage.query.filter_by(user_id=user_id, sender='user', is_read_by_admin=False).update({ChatMessage.is_read_by_admin: True})
        db.session.commit()
        return jsonify([
            {
                'id': m.id,
                'sender': m.sender,
                'text': m.text,
                'image_path': m.image_path,
                'created_at': m.created_at.isoformat()
            } for m in msgs
        ])
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.get('/api/chat/unread')
@login_required
def api_chat_unread():
    if isinstance(current_user, AdminUser):
        # 管理员端：统计所有未读的用户消息数量
        count = ChatMessage.query.filter_by(sender='user', is_read_by_admin=False).count()
        return jsonify({ 'role': 'admin', 'unread': count })
    # 用户端：统计发给该用户的管理员未读
    count = ChatMessage.query.filter_by(user_id=current_user.id, sender='admin', is_read_by_user=False).count()
    return jsonify({ 'role': 'user', 'unread': count })

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
        
        # 检查用户是否被封禁
        if current_user.is_banned:
            logout_user()
            flash('您的账户已被封禁，请联系管理员', 'error')
            return redirect(url_for('login'))
        
        return func(*args, **kwargs)
    return wrapper

def is_valid_email(email: str) -> bool:
    return isinstance(email, str) and '@' in email and '.' in email

@app.before_request
def check_user_ban_status():
    """在每个请求前检查用户封禁状态"""
    if current_user.is_authenticated and isinstance(current_user, User):
        # 重新从数据库获取用户信息，确保状态是最新的
        user = User.query.get(current_user.id)
        if user and user.is_banned:
            logout_user()
            flash('您的账户已被封禁，请联系管理员', 'error')
            return redirect(url_for('login'))

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
    # 站点封面与全局设置
    cover = get_setting('cover_image')
    site_title = get_setting('site_title', 'Moly代购网站')
    footer_text = get_setting('footer_text', '保留所有权利.')
    wechat_qr = get_setting('wechat_qr')
    return dict(
        is_admin=is_admin,
        is_user=is_user,
        current_year=datetime.utcnow().year,
        site_cover=cover,
        site_title=site_title,
        footer_text=footer_text,
        wechat_qr=wechat_qr,
    )

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

def check_banned_users():
    """检查并强制登出被封禁的用户"""
    with app.app_context():
        try:
            # 获取所有被封禁的用户
            banned_users = User.query.filter_by(is_banned=True).all()
            
            if banned_users:
                print(f"发现 {len(banned_users)} 个被封禁的用户")
                # 这里我们无法直接操作Flask-Login的会话
                # 但可以通过其他方式处理，比如记录日志或发送通知
                for user in banned_users:
                    print(f"用户 {user.email} 已被封禁，需要强制登出")
                
        except Exception as e:
            print(f"检查封禁用户时出错: {e}")

# 启动定时任务
scheduler = BackgroundScheduler()
scheduler.add_job(func=auto_cancel_unpaid_orders, trigger="interval", hours=1)
scheduler.add_job(func=cleanup_expired_verification_codes, trigger="interval", hours=6)  # 每6小时清理一次
scheduler.add_job(func=check_banned_users, trigger="interval", minutes=5)  # 每5分钟检查一次封禁用户
scheduler.start()
atexit.register(lambda: scheduler.shutdown())

# 路由
@app.route('/')
def index():
    # 上架优先，按更新时间倒序；下架置后
    status_order = db.case((Product.status=='down', 1), else_=0)
    products = Product.query.filter(Product.status.in_(['up','down'])).order_by(status_order.asc(), Product.updated_at.desc()).all()
    # 统计销量（仅统计已付款订单）
    sales_rows = db.session.query(
        OrderItem.product_id.label('pid'),
        func.coalesce(func.sum(OrderItem.qty), 0).label('total_qty')
    ).join(Order, OrderItem.order_id==Order.id).\
      filter(Order.is_paid==True, OrderItem.product_id.isnot(None)).\
      group_by(OrderItem.product_id).all()
    sales_map = {row.pid: int(row.total_qty or 0) for row in sales_rows}
    # 优化：批量计算最低展示价，减少 JSON 解析次数
    min_price_map = {}
    for p in products:
        base = float(p.price_rmb)
        if p.variants:
            try:
                variants = json.loads(p.variants)
                if variants:
                    min_price_map[p.id] = min(base + float(v.get('extra_price') or 0) for v in variants)
                else:
                    min_price_map[p.id] = base
            except (json.JSONDecodeError, ValueError, TypeError):
                min_price_map[p.id] = base
        else:
            min_price_map[p.id] = base
    return render_template('frontend/index.html', products=products, sales_map=sales_map, min_price_map=min_price_map)

@app.route('/product/<int:product_id>')
def product_detail(product_id: int):
    p = Product.query.get_or_404(product_id)
    imgs = []
    try:
        imgs = json.loads(p.images) if p.images else []
    except Exception:
        imgs = []
    variants = []
    try:
        variants = json.loads(p.variants) if p.variants else []
    except Exception:
        variants = []
    return render_template('frontend/product_detail.html', p=p, imgs=imgs, variants=variants)

@app.route('/admin/products/<int:product_id>/stats')
@admin_required
def admin_product_stats(product_id: int):
    p = Product.query.get_or_404(product_id)
    # 各规格销量与下单数（已付款），利润使用订单项历史单价/单成本
    rows = db.session.query(
        OrderItem.variant_name.label('vname'),
        func.count(func.distinct(OrderItem.order_id)).label('order_count'),
        func.coalesce(func.sum(OrderItem.qty), 0).label('total_qty')
    ).join(Order, OrderItem.order_id==Order.id).\
      filter(OrderItem.product_id==p.id, Order.is_paid==True).\
      group_by(OrderItem.variant_name).all()

    # 获取各规格对应的订单号列表
    order_map = {}
    order_rows = db.session.query(
        OrderItem.variant_name, OrderItem.order_id
    ).join(Order, OrderItem.order_id==Order.id).\
      filter(OrderItem.product_id==p.id, Order.is_paid==True).\
      group_by(OrderItem.variant_name, OrderItem.order_id).all()
    for vname, oid in order_rows:
        order_no = Order.query.get(oid).order_no  # small N, acceptable
        order_map.setdefault(vname or '', []).append(order_no)

    detail = []
    total_profit = 0.0
    for vname, order_count, total_qty in rows:
        qty = int(total_qty or 0)
        # 该规格的已付款订单项
        paid_items = db.session.query(OrderItem.qty, OrderItem.unit_price, OrderItem.unit_cost).\
            join(Order, OrderItem.order_id==Order.id).\
            filter(OrderItem.product_id==p.id, Order.is_paid==True, OrderItem.variant_name==(vname)).all()
        unit_profit_example = None
        profit = 0.0
        for q, up, uc in paid_items:
            upf = float(up or 0)
            ucf = float(uc or 0)
            if unit_profit_example is None and (up is not None or uc is not None):
                unit_profit_example = upf - ucf
            profit += (upf - ucf) * int(q or 0)
        # 如果示例仍为空且数量>0，用平均单件利润（总利润/总数量）展示更直观
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
    # 计算每条目的单价（含规格加价）与小计
    display = []
    for ci, p in items:
        unit = float(p.price_rmb)
        try:
            if ci.variant_name and p.variants:
                vs = json.loads(p.variants)
                for v in vs:
                    if v.get('name') == ci.variant_name:
                        unit += float(v.get('extra_price') or 0)
                        break
        except Exception:
            pass
        display.append({'item': ci, 'product': p, 'unit_price': unit, 'subtotal': unit * ci.qty})
    return render_template('frontend/cart.html', cart_items=display)

@app.route('/cart/add/<int:product_id>', methods=['POST'])
@login_required
@user_required
def add_to_cart(product_id: int):
    product = Product.query.get_or_404(product_id)
    if product.status != 'up':
        flash('该商品未上架，无法加入购物车', 'error')
        return redirect(url_for('index'))
    qty = int(request.form.get('qty', '1') or '1')
    variant_name = request.form.get('variant_name') or None
    qty = max(1, min(qty, 999))
    item = CartItem.query.filter_by(user_id=current_user.id, product_id=product_id, variant_name=variant_name).first()
    if item:
        item.qty += qty
    else:
        item = CartItem(user_id=current_user.id, product_id=product_id, qty=qty, variant_name=variant_name)
        db.session.add(item)
    db.session.commit()
    vtip = f'（{variant_name}）' if variant_name else ''
    flash(f'“{product.title}{vtip}” ×{qty} 已加入购物车', 'success')
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
    # 校验收货地址是否完整（邮编可空）
    addr = current_user.address if hasattr(current_user, 'address') else None
    if not addr or not addr.name or not addr.phone or not addr.address_text:
        flash('请先完善收货地址（收货人、手机号、地址），再提交订单', 'error')
        return redirect(url_for('profile_address'))
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

    # 计算商品金额，并为每个条目计算当时单价/单成本
    amount_items = 0.0
    per_item_prices = {}
    for (ci, p) in cart_items:
        # 规格可能存在加价：从 p.variants 中查找
        unit_price = float(p.price_rmb)
        unit_cost = float(p.cost_price_rmb or 0)
        try:
            variants = json.loads(p.variants) if p.variants else []
            if ci.variant_name:
                for v in variants:
                    if v.get('name') == ci.variant_name:
                        unit_price += float(v.get('extra_price') or 0)
                        # 若未来支持 extra_cost，可在此叠加到 unit_cost
                        break
        except Exception:
            pass
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
        up, uc = per_item_prices.get(ci.id, (float(p.price_rmb), float(p.cost_price_rmb or 0)))
        oi = OrderItem(
            order_id=order.id,
            product_id=p.id,
            name=p.title,
            spec_note=p.note or '',
            qty=ci.qty,
            variant_name=ci.variant_name,
            unit_price=up,
            unit_cost=uc,
        )
        db.session.add(oi)
        db.session.delete(ci)
    db.session.commit()
    flash(f'订单已提交，订单号：{order_no}，请前往订单详情查看并付款', 'success')
    return redirect(url_for('order_detail', order_no=order_no))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email_or_username = request.form['email'].strip()
        password = request.form['password']
        
        # 判断是邮箱还是用户名
        if '@' in email_or_username:
            # 邮箱登录
            user = User.query.filter_by(email=email_or_username).first()
        else:
            # 用户名登录
            user = User.query.filter_by(username=email_or_username).first()
        
        if user and check_password_hash(user.password_hash, password):
            if user.is_banned:
                flash('您的账户已被封禁，请联系管理员', 'error')
            else:
                remember = True
                login_user(user, remember=remember, duration=timedelta(days=7))
                user.last_login_at = datetime.utcnow()
                db.session.commit()
                return redirect(url_for('index'))
        else:
            flash('邮箱/用户名或密码错误', 'error')
    
    return render_template('frontend/login.html')

@app.route('/register', methods=['GET', 'POST'])
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

        # 验证用户名（如果提供）
        if username:
            import re
            if not re.match(r'^[a-zA-Z0-9_]{3,20}$', username):
                flash('用户名只能包含字母、数字和下划线，长度3-20位', 'error')
                return render_template('frontend/register.html')
            
            if User.query.filter_by(username=username).first():
                flash('该用户名已被使用', 'error')
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
            username=username if username else None,
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

    # 计算每个条目的单价（优先使用历史存储；否则按当前规格计算）
    try:
        for it in order.items:
            unit = float(it.unit_price or 0)
            if unit:
                it.unit_price = unit
                continue
            p = Product.query.get(it.product_id) if it.product_id else None
            if p:
                unit = float(p.price_rmb or 0)
                try:
                    if it.variant_name and p.variants:
                        for v in json.loads(p.variants):
                            if v.get('name') == it.variant_name:
                                unit += float(v.get('extra_price') or 0)
                                break
                except Exception:
                    pass
            it.unit_price = unit
    except Exception:
        pass
    
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
        # 仅允许环境变量指定的管理员用户名登录，避免历史/多余账号（如 admin）可用
        try:
            expected_username = _require_env('ADMIN_USERNAME')
        except Exception:
            expected_username = None
        if not expected_username or username != expected_username:
            flash('用户名或密码错误', 'error')
            return render_template('admin/login.html')

        admin = AdminUser.query.filter_by(username=expected_username).first()
        
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
    
    # 优化：分别查询不同表的统计，避免复杂的多表连接
    from sqlalchemy import func as SAfunc
    
    # 订单统计
    order_stats = db.session.query(
        SAfunc.count(Order.id).label('total_orders'),
        SAfunc.count(Order.id).filter(Order.is_paid==True).label('paid_orders'),
        SAfunc.count(Order.id).filter(Order.status=='pending').label('pending_orders'),
        SAfunc.count(Order.id).filter(Order.status=='processing').label('processing_orders')
    ).first()
    
    # 用户统计
    user_stats = db.session.query(
        SAfunc.count(User.id).label('total_users'),
        SAfunc.count(User.id).filter(User.is_banned==True).label('banned_users')
    ).first()
    
    # 商品统计
    product_count = Product.query.count()
    
    total_orders = order_stats.total_orders or 0
    paid_orders = order_stats.paid_orders or 0
    pending_orders = order_stats.pending_orders or 0
    processing_orders = order_stats.processing_orders or 0
    total_users = user_stats.total_users or 0
    banned_users = user_stats.banned_users or 0

    # 收入统计（分别查询，避免 SQLite FILTER 问题）
    today = datetime.utcnow().date()
    today_start = datetime(today.year, today.month, today.day)
    
    # 已付款订单的收入统计
    paid_orders = Order.query.filter_by(is_paid=True)
    revenue_total_due = float(paid_orders.with_entities(SAfunc.sum(Order.amount_due)).scalar() or 0)
    revenue_total_paid = float(paid_orders.with_entities(SAfunc.sum(Order.amount_paid)).scalar() or 0)
    
    # 未付款订单的应收统计
    receivable_pending = float(Order.query.filter_by(is_paid=False).with_entities(SAfunc.sum(Order.amount_due)).scalar() or 0)
    
    # 今日统计
    today_orders = Order.query.filter(Order.created_at >= today_start).count()
    today_revenue_due = float(paid_orders.filter(Order.paid_at >= today_start).with_entities(SAfunc.sum(Order.amount_due)).scalar() or 0)
    today_revenue_paid = float(paid_orders.filter(Order.paid_at >= today_start).with_entities(SAfunc.sum(Order.amount_paid)).scalar() or 0)

    # 未读消息和热销商品（并行查询）
    unread_user_msgs = ChatMessage.query.filter_by(sender='user', is_read_by_admin=False).count()
    
    # Top5 商品销量（已付款订单）
    top_rows = db.session.query(
        Product.title, SAfunc.coalesce(SAfunc.sum(OrderItem.qty),0).label('qty')
    ).join(OrderItem, OrderItem.product_id==Product.id).join(Order, OrderItem.order_id==Order.id).\
      filter(Order.is_paid==True).group_by(Product.id).order_by(SAfunc.sum(OrderItem.qty).desc()).limit(5).all()

    # 当前版本
    current_version = Version.query.filter_by(is_current=True).first()
    
    return render_template('admin/dashboard.html',
                         total_orders=total_orders,
                         paid_orders=paid_orders,
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
                         now=datetime.utcnow())

@app.route('/admin/products')
@admin_required
def admin_products():
    
    status_order = db.case((Product.status=='down', 1), else_=0)
    # 订单统计（仅统计已付款订单）
    sub_orders = db.session.query(
        OrderItem.product_id.label('pid'),
        func.count(func.distinct(OrderItem.order_id)).label('order_count'),
        func.coalesce(func.sum(OrderItem.qty), 0).label('total_qty')
    ).join(Order, OrderItem.order_id==Order.id).\
      filter(Order.is_paid==True).\
      group_by(OrderItem.product_id).subquery()

    # 各规格销量（已付款）
    variant_qty_rows = db.session.query(
        OrderItem.product_id, OrderItem.variant_name, func.coalesce(func.sum(OrderItem.qty), 0)
    ).join(Order, OrderItem.order_id==Order.id).\
      filter(Order.is_paid==True).\
      group_by(OrderItem.product_id, OrderItem.variant_name).all()
    qty_by_variant = {}
    for pid, vname, q in variant_qty_rows:
        qty_by_variant.setdefault(pid, {})[vname or ''] = int(q or 0)

    rows = db.session.query(Product, sub_orders.c.order_count, sub_orders.c.total_qty).\
        outerjoin(sub_orders, Product.id==sub_orders.c.pid).\
        order_by(db.desc(Product.pinned), status_order.asc(), Product.updated_at.desc()).all()

    # 优化：批量查询所有商品的利润，避免 N+1 查询
    product_ids = [p.id for p, _, _ in rows]
    profit_data = {}
    if product_ids:
        profit_rows = db.session.query(
            OrderItem.product_id,
            func.sum((OrderItem.unit_price - OrderItem.unit_cost) * OrderItem.qty).label('total_profit')
        ).join(Order, OrderItem.order_id==Order.id).\
          filter(OrderItem.product_id.in_(product_ids), Order.is_paid==True).\
          group_by(OrderItem.product_id).all()
        profit_data = {row.product_id: float(row.total_profit or 0) for row in profit_rows}

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

# 用户管理
@app.route('/admin/users')
@login_required
@admin_required
def admin_users():
    users = User.query.order_by(User.created_at.desc()).all()
    return render_template('admin/users.html', users=users)

@app.route('/admin/users/new', methods=['GET', 'POST'])
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

        # 验证用户名（如果提供）
        if username:
            import re
            if not re.match(r'^[a-zA-Z0-9_]{3,20}$', username):
                flash('用户名只能包含字母、数字和下划线，长度3-20位', 'error')
                return render_template('admin/user_new.html', form=request.form)
            
            if User.query.filter_by(username=username).first():
                flash('该用户名已被使用', 'error')
                return render_template('admin/user_new.html', form=request.form)

        user = User(
            email=email,
            username=username if username else None,
            password_hash=generate_password_hash(password),
            notes=notes if notes else None
        )
        db.session.add(user)
        db.session.flush()

        # 可选创建地址（若信息完整则创建）
        if name and phone and address_text:
            addr = Address(
                user_id=user.id,
                name=name,
                phone=phone,
                address_text=address_text,
                postal_code=postal_code
            )
            db.session.add(addr)

        db.session.commit()
        flash('用户已创建', 'success')
        return redirect(url_for('admin_users'))

    return render_template('admin/user_new.html')

@app.route('/admin/users/<int:user_id>/edit', methods=['GET', 'POST'])
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
        exists = User.query.filter(User.email == email, User.id != user.id).first()
        if exists:
            flash('该邮箱已被使用', 'error')
            return render_template('admin/user_form.html', user=user)
        
        # 验证用户名（如果提供）
        if username:
            import re
            if not re.match(r'^[a-zA-Z0-9_]{3,20}$', username):
                flash('用户名只能包含字母、数字和下划线，长度3-20位', 'error')
                return render_template('admin/user_form.html', user=user)
            
            exists_username = User.query.filter(User.username == username, User.id != user.id).first()
            if exists_username:
                flash('该用户名已被使用', 'error')
                return render_template('admin/user_form.html', user=user)
        
        user.email = email
        user.username = username if username else None
        user.notes = notes if notes else None
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

@app.route('/admin/users/<int:user_id>/ban')
@login_required
@admin_required
def admin_user_ban(user_id: int):
    user = User.query.get_or_404(user_id)
    user.is_banned = True
    db.session.commit()
    flash(f'用户 {user.email} 已被封禁', 'success')
    return redirect(url_for('admin_users'))

@app.route('/admin/users/<int:user_id>/unban')
@login_required
@admin_required
def admin_user_unban(user_id: int):
    user = User.query.get_or_404(user_id)
    user.is_banned = False
    db.session.commit()
    flash(f'用户 {user.email} 已解封', 'success')
    return redirect(url_for('admin_users'))

@app.route('/admin/products/new', methods=['GET', 'POST'])
@admin_required
def admin_new_product():
    
    if request.method == 'POST':
        title = request.form['title']
        note = request.form.get('note', '')
        status = request.form.get('status', 'up')
        
        # 处理图片上传（商品通用图片）
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
        
        # 规格解析：接收 variants_text（JSON：[{name, price, cost}...]）
        variants_text = request.form.get('variants_text', '').strip()
        raw_list = []
        try:
            raw_list = json.loads(variants_text) if variants_text else []
        except Exception:
            raw_list = []
        # 基准价为所有规格展示价的最小值
        base_price = 0.0
        if raw_list:
            prices = [float(x.get('price') or 0) for x in raw_list if (x.get('price') is not None)]
            base_price = min(prices) if prices else 0.0
        base_cost = 0.0
        if raw_list:
            costs = [float(x.get('cost') or 0) for x in raw_list if (x.get('cost') is not None)]
            base_cost = min(costs) if costs else 0.0
        # 处理规格图片上传：与 v_name/v_price/v_cost 行按序对应
        variants = []
        # 根据序号逐一取文件 v_image_0, v_image_1 ...
        idx = 0
        for x in raw_list:
            name = (x.get('name') or '').strip()
            price = float(x.get('price') or 0)
            extra = price - base_price
            image_rel = None
            f = request.files.get(f'v_image_{idx}')
            if f and f.filename and allowed_file(f.filename):
                fname = secure_filename(f.filename)
                ts = datetime.now().strftime('%Y%m%d_%H%M%S_')
                fname = ts + fname
                fpath = os.path.join(app.config['UPLOAD_FOLDER'], 'products', fname)
                f.save(fpath)
                image_rel = f'products/{fname}'
            idx += 1
            v = {'name': name, 'extra_price': extra}
            if image_rel:
                v['image'] = image_rel
            variants.append(v)

        product = Product(
            title=title,
            price_rmb=base_price,
            cost_price_rmb=base_cost,
            note=note,
            status=status,
            images=json.dumps(uploaded_images) if uploaded_images else None,
            variants=json.dumps(variants) if variants else None
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
        try:
            print('[EDIT_PRODUCT] POST received', {'keys': list(request.form.keys())})
            # 仅修改上下架状态的快捷操作（列表页表单只提交 status）
            if 'title' not in request.form and 'price_rmb' not in request.form:
                new_status = request.form.get('status')
                if new_status in ['up', 'down']:
                    product.status = new_status
                    db.session.commit()
                    flash('商品状态已更新', 'success')
                    return redirect(url_for('admin_products'))
            
            # 正常编辑表单
            product.title = request.form.get('title', product.title)
            product.note = request.form.get('note', '')
            product.status = request.form.get('status', 'up')
            # 规格（JSON：[{name, price, cost}...]）并重算基准价
            variants_text = request.form.get('variants_text', '').strip()
            raw_list = []
            try:
                raw_list = json.loads(variants_text) if variants_text else []
            except Exception as e:
                print('[EDIT_PRODUCT] variants_text parse error', e, variants_text)
                raw_list = []
            if raw_list:
                prices = [float(x.get('price') or 0) for x in raw_list if (x.get('price') is not None)]
                costs = [float(x.get('cost') or 0) for x in raw_list if (x.get('cost') is not None)]
                base_price = min(prices) if prices else 0.0
                base_cost = min(costs) if costs else 0.0
                variants = []
                idx = 0
                for x in raw_list:
                    name = (x.get('name') or '').strip()
                    price = float(x.get('price') or 0)
                    extra = price - base_price
                    image_rel = None
                    f = request.files.get(f'v_image_{idx}')
                    if f and f.filename and allowed_file(f.filename):
                        fname = secure_filename(f.filename)
                        ts = datetime.now().strftime('%Y%m%d_%H%M%S_')
                        fname = ts + fname
                        fpath = os.path.join(app.config['UPLOAD_FOLDER'], 'products', fname)
                        f.save(fpath)
                        image_rel = f'products/{fname}'
                    else:
                        existed = request.form.get(f'v_image_existing_{idx}')
                        if existed:
                            image_rel = existed
                    idx += 1
                    v = {'name': name, 'extra_price': extra}
                    if image_rel:
                        v['image'] = image_rel
                    variants.append(v)
                product.price_rmb = base_price
                product.cost_price_rmb = base_cost
                product.variants = json.dumps(variants) if variants else None
            
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
            print('[EDIT_PRODUCT] commit done for product', product.id)
            flash('商品更新成功', 'success')
            return redirect(url_for('admin_products'))
        except Exception as e:
            db.session.rollback()
            print('[EDIT_PRODUCT] error:', e)
            flash(f'保存失败：{e}', 'error')
            return render_template('admin/product_form.html', product=product)
        except Exception as e:
            db.session.rollback()
            print('[EDIT_PRODUCT] error:', e)
            flash(f'保存失败：{e}', 'error')
            return render_template('admin/product_form.html', product=product)
    
    return render_template('admin/product_form.html', product=product)

@app.post('/admin/products/<int:product_id>/delete-image')
@admin_required
def admin_product_delete_image(product_id):
    product = Product.query.get_or_404(product_id)
    image_url = request.form.get('image_url')
    if not image_url:
        return redirect(url_for('admin_edit_product', product_id=product.id))
    try:
        imgs = json.loads(product.images) if product.images else []
        if image_url in imgs:
            imgs.remove(image_url)
            product.images = json.dumps(imgs)
            # 删除物理文件
            abs_path = os.path.join(app.config['UPLOAD_FOLDER'], image_url.replace('/', os.sep))
            if os.path.exists(abs_path):
                try:
                    os.remove(abs_path)
                except Exception:
                    pass
            db.session.commit()
            flash('图片已删除', 'success')
    except Exception as e:
        flash(f'删除失败: {e}', 'error')
    return redirect(url_for('admin_edit_product', product_id=product.id))

@app.post('/admin/products/<int:product_id>/pin')
@admin_required
def admin_product_pin(product_id: int):
    p = Product.query.get_or_404(product_id)
    p.pinned = True
    p.updated_at = datetime.utcnow()
    db.session.commit()
    flash('已置顶该商品', 'success')
    return redirect(url_for('admin_products'))

@app.post('/admin/products/<int:product_id>/images/upload')
@admin_required
def admin_product_upload_image(product_id: int):
    product = Product.query.get_or_404(product_id)
    file = request.files.get('image')
    if not file or not file.filename or not allowed_file(file.filename):
        return jsonify({'ok': False, 'msg': '请选择有效图片'}), 400
    try:
        filename = secure_filename(file.filename)
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S_')
        filename = timestamp + filename
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], 'products', filename)
        file.save(filepath)
        rel = f'products/{filename}'
        # 追加到 product.images
        imgs = []
        try:
            imgs = json.loads(product.images) if product.images else []
        except Exception:
            imgs = []
        imgs.append(rel)
        product.images = json.dumps(imgs)
        db.session.commit()
        return jsonify({'ok': True, 'url': url_for('static', filename='uploads/' + rel), 'rel': rel})
    except Exception as e:
        db.session.rollback()
        return jsonify({'ok': False, 'msg': str(e)}), 500

@app.post('/admin/products/<int:product_id>/delete')
@admin_required
def admin_product_delete(product_id: int):
    product = Product.query.get_or_404(product_id)
    try:
        # 清理购物车引用
        CartItem.query.filter_by(product_id=product.id).delete()
        # 订单条目解除关联而不删除历史记录
        for oi in OrderItem.query.filter_by(product_id=product.id).all():
            oi.product_id = None
        # 删除商品通用图片
        try:
            imgs = json.loads(product.images) if product.images else []
            for rel in imgs:
                abs_path = os.path.join(app.config['UPLOAD_FOLDER'], rel.replace('/', os.sep))
                if os.path.exists(abs_path):
                    try:
                        os.remove(abs_path)
                    except Exception:
                        pass
        except Exception:
            pass
        # 删除规格图片
        try:
            vs = json.loads(product.variants) if product.variants else []
            for v in vs:
                rel = v.get('image')
                if rel:
                    abs_path = os.path.join(app.config['UPLOAD_FOLDER'], rel.replace('/', os.sep))
                    if os.path.exists(abs_path):
                        try:
                            os.remove(abs_path)
                        except Exception:
                            pass
        except Exception:
            pass

        db.session.delete(product)
        db.session.commit()
        flash('商品已删除', 'success')
        return redirect(url_for('admin_products'))
    except Exception as e:
        db.session.rollback()
        flash(f'删除失败：{e}', 'error')
        return redirect(url_for('admin_edit_product', product_id=product.id))

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
    # 计算每个条目的单价（优先使用历史存储；否则按当前规格计算）
    try:
        for it in order.items:
            unit = float(it.unit_price or 0)
            if unit:
                it.unit_price = unit
                continue
            p = Product.query.get(it.product_id) if it.product_id else None
            if p:
                unit = float(p.price_rmb or 0)
                try:
                    if it.variant_name and p.variants:
                        for v in json.loads(p.variants):
                            if v.get('name') == it.variant_name:
                                unit += float(v.get('extra_price') or 0)
                                break
                except Exception:
                    pass
            it.unit_price = unit
    except Exception:
        pass
    return render_template('admin/order_detail.html', order=order)

@app.route('/admin/orders/<order_no>/mark-paid', methods=['POST'])
@admin_required
def admin_mark_paid(order_no):
    
    order = Order.query.filter_by(order_no=order_no).first_or_404()
    # 读取实收金额，默认使用应付金额
    try:
        amount_paid = float(request.form.get('amount_paid') or order.amount_due or 0)
    except Exception:
        amount_paid = float(order.amount_due or 0)
    order.amount_paid = amount_paid
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
    order.amount_paid = 0
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
    """采购清单预览：展示已付款订单（默认processing），支持时间与关键字筛选。
    适配规格：若有 OrderItem.variant_name 优先展示，否则回退到 spec_note。
    商品名：若关联商品，展示商品库标题，否则用订单项名称。
    """
    # 筛选参数
    start_date = request.args.get('start_date')
    end_date = request.args.get('end_date')
    keyword = request.args.get('q', '')
    status = request.args.get('status', 'processing')  # processing/all

    orders_q = Order.query.filter(Order.is_paid == True)
    if status != 'all':
        orders_q = orders_q.filter(Order.status == 'processing')
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

    # 展平到条目层（适配规格与商品名）
    rows = []
    for order in orders:
        user = order.user
        addr = user.address
        for item in order.items:
            # 仅统计该订单的条目
            # 名称：商品库优先
            display_name = item.name
            if item.product_id:
                p = Product.query.get(item.product_id)
                if p:
                    display_name = p.title
            # 规格：variant_name 优先
            spec = item.variant_name or item.spec_note or ''
            rows.append({
                'order_no': order.order_no,
                'created_at': order.created_at,
                'email': user.email,
                'receiver': addr.name if addr else '',
                'phone': addr.phone if addr else '',
                'address': addr.address_text if addr else '',
                'name': display_name,
                'spec': spec,
                'qty': item.qty,
                'source': '商品库' if item.product_id else '自定义'
            })

    return render_template('admin/purchase_preview.html', rows=rows, start_date=start_date or '', end_date=end_date or '', keyword=keyword, status=status)

@app.route('/admin/purchase-list/download', methods=['GET'])
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
    writer.writerow(['订单号','下单时间','用户邮箱','收货人','手机号','地址','商品名称','规格','数量','来源'])
    for order in orders:
        user = order.user
        addr = user.address
        receiver = addr.name if addr else ''
        phone = addr.phone if addr else ''
        addr_text = addr.address_text if addr else ''
        for item in order.items:
            display_name = item.name
            if item.product_id:
                p = Product.query.get(item.product_id)
                if p:
                    display_name = p.title
            spec = item.variant_name or item.spec_note or ''
            writer.writerow([
                order.order_no,
                order.created_at.strftime('%Y-%m-%d %H:%M:%S'),
                user.email,
                receiver,
                phone,
                addr_text,
                display_name,
                spec,
                item.qty,
                ('商品库' if item.product_id else '自定义'),
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

@app.route('/admin/basic-settings', methods=['GET', 'POST'])
@admin_required
def admin_basic_settings():
    if request.method == 'POST':
        title = request.form.get('site_title', '').strip() or 'Moly代购网站'
        footer = request.form.get('footer_text', '').strip() or '保留所有权利.'
        cover = request.form.get('cover_image', '')
        wechat_qr = request.form.get('wechat_qr', '')
        
        set_setting('site_title', title)
        set_setting('footer_text', footer)
        if cover:
            set_setting('cover_image', cover)
        if wechat_qr:
            set_setting('wechat_qr', wechat_qr)
        flash('基础设定已保存', 'success')
        return redirect(url_for('admin_basic_settings'))
    return render_template('admin/basic_settings.html',
                           site_title=get_setting('site_title', 'Moly代购网站'),
                           footer_text=get_setting('footer_text', '保留所有权利.'),
                           cover_image=get_setting('cover_image'),
                           wechat_qr=get_setting('wechat_qr'))

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

@app.route('/admin/settings/wechat-qr', methods=['POST'])
@admin_required
def admin_update_wechat_qr():
    if 'wechat_qr' in request.files:
        file = request.files['wechat_qr']
        if file and file.filename and allowed_file(file.filename):
            filename = secure_filename(file.filename)
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S_')
            filename = timestamp + filename
            filepath = os.path.join(app.config['UPLOAD_FOLDER'], 'qrcodes', filename)
            file.save(filepath)
            set_setting('wechat_qr', f'qrcodes/{filename}')
            flash('微信二维码已更新', 'success')
        else:
            flash('请选择有效的图片文件', 'error')
    else:
        flash('未选择文件', 'error')
    return redirect(url_for('admin_basic_settings'))

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

# （安全考虑）已移除清空商品与购物车功能

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
        # 旧库自动迁移：为 Product 添加 cost_price_rmb 列
        try:
            from sqlalchemy import inspect, text
            insp = inspect(db.engine)
            cols = [c['name'] for c in insp.get_columns('product')]
            if 'cost_price_rmb' not in cols:
                db.session.execute(text('ALTER TABLE product ADD COLUMN cost_price_rmb NUMERIC(10,2) DEFAULT 0'))
                db.session.commit()
        except Exception as e:
            print('检查/添加列 cost_price_rmb 失败: ', e)

        # 旧库自动迁移：为 Product 添加 variants 列
        try:
            from sqlalchemy import inspect, text
            insp = inspect(db.engine)
            cols = [c['name'] for c in insp.get_columns('product')]
            if 'variants' not in cols:
                db.session.execute(text('ALTER TABLE product ADD COLUMN variants TEXT'))
                db.session.commit()
            if 'pinned' not in cols:
                db.session.execute(text('ALTER TABLE product ADD COLUMN pinned BOOLEAN DEFAULT 0'))
                db.session.commit()
        except Exception as e:
            print('检查/添加列 variants/pinned 失败: ', e)

        # 旧库自动迁移：为 CartItem / OrderItem 添加 variant_name 列
        try:
            from sqlalchemy import inspect, text
            insp = inspect(db.engine)
            cols_cart = [c['name'] for c in insp.get_columns('cart_item')]
            if 'variant_name' not in cols_cart:
                db.session.execute(text('ALTER TABLE cart_item ADD COLUMN variant_name VARCHAR(100)'))
                db.session.commit()
            cols_oi = [c['name'] for c in insp.get_columns('order_item')]
            if 'variant_name' not in cols_oi:
                db.session.execute(text('ALTER TABLE order_item ADD COLUMN variant_name VARCHAR(100)'))
                db.session.commit()
            # 为订单项增加历史单价/单成本
            cols_oi = [c['name'] for c in insp.get_columns('order_item')]
            if 'unit_price' not in cols_oi:
                db.session.execute(text('ALTER TABLE order_item ADD COLUMN unit_price NUMERIC(10,2)'))
                db.session.commit()
            cols_oi = [c['name'] for c in insp.get_columns('order_item')]
            if 'unit_cost' not in cols_oi:
                db.session.execute(text('ALTER TABLE order_item ADD COLUMN unit_cost NUMERIC(10,2)'))
                db.session.commit()
        except Exception as e:
            print('检查/添加列 variant_name 失败: ', e)

        # 旧库自动迁移：为 User 添加 username 和 notes 列
        try:
            from sqlalchemy import inspect, text
            insp = inspect(db.engine)
            cols_user = [c['name'] for c in insp.get_columns('user')]
            if 'username' not in cols_user:
                db.session.execute(text('ALTER TABLE user ADD COLUMN username VARCHAR(50) UNIQUE'))
                db.session.commit()
                print('已添加 username 列到 user 表')
            if 'notes' not in cols_user:
                db.session.execute(text('ALTER TABLE user ADD COLUMN notes TEXT'))
                db.session.commit()
                print('已添加 notes 列到 user 表')
        except Exception as e:
            print('检查/添加列 username/notes 失败: ', e)

        # 添加性能优化索引
        try:
            db.session.execute(text('CREATE INDEX IF NOT EXISTS idx_order_is_paid ON "order"(is_paid)'))
            db.session.execute(text('CREATE INDEX IF NOT EXISTS idx_order_status ON "order"(status)'))
            db.session.execute(text('CREATE INDEX IF NOT EXISTS idx_order_created_at ON "order"(created_at)'))
            db.session.execute(text('CREATE INDEX IF NOT EXISTS idx_order_paid_at ON "order"(paid_at)'))
            db.session.execute(text('CREATE INDEX IF NOT EXISTS idx_order_item_product_id ON order_item(product_id)'))
            db.session.execute(text('CREATE INDEX IF NOT EXISTS idx_order_item_order_id ON order_item(order_id)'))
            db.session.execute(text('CREATE INDEX IF NOT EXISTS idx_product_status ON product(status)'))
            db.session.execute(text('CREATE INDEX IF NOT EXISTS idx_product_pinned ON product(pinned)'))
            db.session.execute(text('CREATE INDEX IF NOT EXISTS idx_chat_message_sender ON chat_message(sender)'))
            db.session.execute(text('CREATE INDEX IF NOT EXISTS idx_chat_message_is_read ON chat_message(is_read_by_admin)'))
            db.session.commit()
            print('已添加性能优化索引')
        except Exception as idx_error:
            print(f'添加索引时出现错误（可忽略）: {idx_error}')
        
        # 创建或更新管理员账户（强制要求从环境注入，禁止默认值）
        admin_username = _require_env('ADMIN_USERNAME')
        admin_password = _require_env('ADMIN_PASSWORD')
        
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
        
    
    app.run(debug=True, host='0.0.0.0', port=5000)
