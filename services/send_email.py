# 邮件发送服务
import logging
import os
import smtplib
from email.header import Header
from email.mime.text import MIMEText

from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)


def send_email(subject, message_body, receiver_email=None,
               sender_email=None, sender_password=None):
    if receiver_email is None:
        receiver_email = os.getenv('DEFAULT_RECEIVER_EMAIL', 'xingkm2024@163.com')
    if sender_email is None:
        sender_email = os.getenv('SENDER_EMAIL', 'moly_laila@163.com')
    if sender_password is None:
        sender_password = os.getenv('SENDER_PASSWORD', 'QYHDEZFGTPOYGRTG')
    msg = MIMEText(message_body, "plain", "utf-8")
    msg["From"] = Header(sender_email)
    msg["To"] = Header(receiver_email)
    msg["Subject"] = Header(subject)

    server = None
    try:
        smtp_server = os.getenv('SMTP_SERVER', 'smtp.163.com')
        smtp_port = int(os.getenv('SMTP_PORT', '465'))
        server = smtplib.SMTP_SSL(smtp_server, smtp_port)
        server.login(sender_email, sender_password)
        server.sendmail(sender_email, receiver_email, msg.as_string())
        logger.info("邮件发送成功 -> %s", receiver_email)
    except Exception as e:
        logger.exception("邮件发送失败: %s", e)
    finally:
        if server is not None:
            try:
                server.quit()
            except Exception:
                pass
