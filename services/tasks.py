# 定时任务
import logging
from datetime import datetime, timedelta

from core.extensions import db
from core.models import Order, EmailVerification, User
from core.utils import get_setting, restore_order_stock

logger = logging.getLogger(__name__)


def auto_cancel_unpaid_orders(app):
    with app.app_context():
        if get_setting('auto_cancel_enabled', 'true').lower() != 'true':
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
            restore_order_stock(order)
        if unpaid_orders:
            db.session.commit()
            logger.info("自动取消了 %d 个未支付订单", len(unpaid_orders))


def cleanup_expired_verification_codes(app):
    with app.app_context():
        try:
            expired_count = EmailVerification.query.filter(
                EmailVerification.expire_at < datetime.utcnow()
            ).delete()
            if expired_count > 0:
                db.session.commit()
                logger.info("清理了 %d 个过期验证码", expired_count)
        except Exception as e:
            logger.exception("清理过期验证码时出错: %s", e)


def check_banned_users(app):
    with app.app_context():
        try:
            banned_users = User.query.filter_by(is_banned=True).all()
            if banned_users:
                for u in banned_users:
                    logger.debug("用户 %s 已被封禁，需要强制登出", u.email)
        except Exception as e:
            logger.exception("检查封禁用户时出错: %s", e)


def register_scheduler(app):
    """仅当 RUN_SCHEDULER=1 时启动定时任务，避免多 worker 重复执行。"""
    import atexit
    import os
    from apscheduler.schedulers.background import BackgroundScheduler

    if os.getenv('RUN_SCHEDULER', '').lower() not in ('1', 'true', 'yes'):
        return
    scheduler = BackgroundScheduler()
    scheduler.add_job(lambda: auto_cancel_unpaid_orders(app), trigger="interval", hours=1)
    scheduler.add_job(lambda: cleanup_expired_verification_codes(app), trigger="interval", hours=6)
    scheduler.add_job(lambda: check_banned_users(app), trigger="interval", minutes=5)
    scheduler.start()
    atexit.register(lambda: scheduler.shutdown())
    logger.info("定时任务调度器已启动")
