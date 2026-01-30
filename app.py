# 应用入口：创建 app、注册蓝图、user_loader、before_request、context_processor、定时任务
import os
import logging

from flask import Flask
from dotenv import load_dotenv
from werkzeug.security import generate_password_hash

load_dotenv()

# 日志：生产环境 INFO，开发环境 DEBUG
_log_level = os.getenv('FLASK_DEBUG', '').lower() in ('1', 'true', 'yes') and logging.DEBUG or logging.INFO
logging.basicConfig(level=_log_level, format='%(asctime)s %(levelname)s [%(name)s] %(message)s')
logger = logging.getLogger(__name__)

from core.utils import require_env, get_setting, set_setting, register_filters
from core.extensions import db, migrate, login_manager
from core.models import User, AdminUser

# 强制校验环境变量
_SECRET_KEY = require_env('SECRET_KEY', forbidden_values=['your-secret-key-change-in-production'])

app = Flask(__name__)
app.config['SECRET_KEY'] = _SECRET_KEY
app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv('DATABASE_URL', 'sqlite:///daigou.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['UPLOAD_FOLDER'] = os.getenv('UPLOAD_FOLDER', 'static/uploads')
app.config['MAX_CONTENT_LENGTH'] = int(os.getenv('MAX_CONTENT_LENGTH', '52428800'))

os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
for sub in ('products', 'payments', 'qrcodes', 'covers', 'chat'):
    os.makedirs(os.path.join(app.config['UPLOAD_FOLDER'], sub), exist_ok=True)

db.init_app(app)
migrate.init_app(app, db)
login_manager.init_app(app)
login_manager.login_view = 'frontend.login'

# 注册蓝图
from blueprints.frontend import frontend
from blueprints.admin_bp import admin_bp
from blueprints.chat import chat_bp
from blueprints.api_rfid import api_rfid

app.register_blueprint(frontend)
app.register_blueprint(admin_bp)
app.register_blueprint(chat_bp)
app.register_blueprint(api_rfid)


@login_manager.user_loader
def load_user(user_id: str):
    try:
        role, raw_id = user_id.split(':', 1)
        if role == 'admin':
            return AdminUser.query.get(int(raw_id))
        if role == 'user':
            return User.query.get(int(raw_id))
    except Exception:
        pass
    return None


@app.before_request
def check_user_ban_status():
    from flask_login import current_user, logout_user
    from flask import redirect, url_for, flash
    if current_user.is_authenticated and isinstance(current_user, User):
        user = User.query.get(current_user.id)
        if user and user.is_banned:
            logout_user()
            flash('您的账户已被封禁，请联系管理员', 'error')
            return redirect(url_for('frontend.login'))


@app.context_processor
def inject_role_helpers():
    from flask_login import current_user
    from flask_login import AnonymousUserMixin

    def is_admin():
        if isinstance(current_user, AnonymousUserMixin) or not current_user.is_authenticated:
            return False
        return isinstance(current_user._get_current_object(), AdminUser)

    def is_user():
        if isinstance(current_user, AnonymousUserMixin) or not current_user.is_authenticated:
            return False
        return isinstance(current_user._get_current_object(), User)

    return dict(
        is_admin=is_admin,
        is_user=is_user,
        current_year=__import__('datetime').datetime.utcnow().year,
        site_cover=get_setting('cover_image'),
        site_title=get_setting('site_title', 'Moly代购网站'),
        footer_text=get_setting('footer_text', '保留所有权利.'),
        wechat_qr=get_setting('wechat_qr'),
    )


register_filters(app)

from services.tasks import register_scheduler

# 开发直接 python app.py 时默认启动定时任务；生产用 Gunicorn 时需显式 RUN_SCHEDULER=1 且单 worker
if __name__ != '__main__' and os.getenv('RUN_SCHEDULER', '').lower() in ('1', 'true', 'yes'):
    register_scheduler(app)


if __name__ == '__main__':
    os.environ.setdefault('RUN_SCHEDULER', '1')
    register_scheduler(app)
    from sqlalchemy import inspect, text

    with app.app_context():
        db.create_all()

        def _cols(table):
            try:
                return [c['name'] for c in inspect(db.engine).get_columns(table)]
            except Exception:
                return []

        # 旧库自动迁移
        if 'cost_price_rmb' not in _cols('product'):
            try:
                db.session.execute(text('ALTER TABLE product ADD COLUMN cost_price_rmb NUMERIC(10,2) DEFAULT 0'))
                db.session.commit()
            except Exception as e:
                logger.warning('检查/添加列 cost_price_rmb 失败: %s', e)
        if 'pinned' not in _cols('product'):
            try:
                db.session.execute(text('ALTER TABLE product ADD COLUMN pinned BOOLEAN DEFAULT 0'))
                db.session.commit()
            except Exception as e:
                logger.warning('检查/添加列 product.pinned 失败: %s', e)
        if 'variant_name' not in _cols('cart_item'):
            try:
                db.session.execute(text('ALTER TABLE cart_item ADD COLUMN variant_name VARCHAR(100)'))
                db.session.commit()
            except Exception as e:
                logger.warning('检查/添加列 cart_item.variant_name 失败: %s', e)
        for col, spec in [
            ('variant_name', 'VARCHAR(100)'),
            ('unit_price', 'NUMERIC(10,2)'),
            ('unit_cost', 'NUMERIC(10,2)'),
        ]:
            if col not in _cols('order_item'):
                try:
                    db.session.execute(text(f'ALTER TABLE order_item ADD COLUMN {col} {spec}'))
                    db.session.commit()
                except Exception as e:
                    logger.warning('检查/添加列 order_item.%s 失败: %s', col, e)
        for col, spec in [('username', 'VARCHAR(50) UNIQUE'), ('notes', 'TEXT')]:
            if col not in _cols('user'):
                try:
                    db.session.execute(text(f'ALTER TABLE user ADD COLUMN {col} {spec}'))
                    db.session.commit()
                except Exception as e:
                    logger.warning('检查/添加列 user.%s 失败: %s', col, e)

        # 性能索引
        for stmt in [
            'CREATE INDEX IF NOT EXISTS idx_order_is_paid ON "order"(is_paid)',
            'CREATE INDEX IF NOT EXISTS idx_order_status ON "order"(status)',
            'CREATE INDEX IF NOT EXISTS idx_order_created_at ON "order"(created_at)',
            'CREATE INDEX IF NOT EXISTS idx_order_paid_at ON "order"(paid_at)',
            'CREATE INDEX IF NOT EXISTS idx_order_item_product_id ON order_item(product_id)',
            'CREATE INDEX IF NOT EXISTS idx_order_item_order_id ON order_item(order_id)',
            'CREATE INDEX IF NOT EXISTS idx_product_status ON product(status)',
            'CREATE INDEX IF NOT EXISTS idx_product_pinned ON product(pinned)',
            'CREATE INDEX IF NOT EXISTS idx_chat_message_sender ON chat_message(sender)',
            'CREATE INDEX IF NOT EXISTS idx_chat_message_is_read ON chat_message(is_read_by_admin)',
        ]:
            try:
                db.session.execute(text(stmt))
                db.session.commit()
            except Exception as err:
                logger.debug('添加索引（可忽略）: %s', err)

        admin_username = require_env('ADMIN_USERNAME')
        admin_password = require_env('ADMIN_PASSWORD')
        admin = AdminUser.query.filter_by(username=admin_username).first()
        if not admin:
            admin = AdminUser(username=admin_username, password_hash=generate_password_hash(admin_password))
            db.session.add(admin)
            db.session.commit()
            logger.info("管理员账户已创建：%s", admin_username)
        else:
            admin.password_hash = generate_password_hash(admin_password)
            db.session.commit()
            logger.info("管理员密码已更新：%s", admin_username)

    app.run(debug=os.getenv('FLASK_DEBUG', '1').lower() in ('1', 'true', 'yes'), host='0.0.0.0', port=int(os.getenv('PORT', '5000')))
