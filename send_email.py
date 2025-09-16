
import smtplib
import os
from email.mime.text import MIMEText
from email.header import Header
from dotenv import load_dotenv

# 加载环境变量
load_dotenv()

def send_email(subject, message_body, receiver_email=None,
               sender_email=None, sender_password=None):
    # 从环境变量获取默认值
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

    try:
        # 从环境变量获取SMTP服务器配置
        smtp_server = os.getenv('SMTP_SERVER', 'smtp.163.com')
        smtp_port = int(os.getenv('SMTP_PORT', '465'))
        
        server = smtplib.SMTP_SSL(smtp_server, smtp_port)
        server.login(sender_email, sender_password)
        server.sendmail(sender_email, receiver_email, msg.as_string())
        print("✔️ 邮件发送成功")
    except Exception as e:
        print("❌ 邮件发送失败:", e)
    finally:
        server.quit()
