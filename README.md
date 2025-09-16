# Moly 代购网站（本地版）

一个极简的个人代购管理系统，支持单管理员后台、用户下单（由管理员创建）、付款截图核验、采购清单导出、自动取消未支付、封面图与深浅主题切换。已在 Windows 环境实现，可平滑迁移到 Linux。

## 功能概览
- 前台：注册/登录、唯一收货地址、订单列表与详情、付款截图上传、购物车与提交订单、取消订单、深浅主题切换
- 后台：管理员登录、商品管理（上下架/多图）、订单管理（创建/标记付款/状态流转）、采购清单预览与下载、系统设置（收款二维码/自动取消/首页封面）
- 任务：APScheduler 定时任务自动取消超时未付款（默认 24h）

## 技术栈
Flask + SQLAlchemy + Flask-Login + Bootstrap 5 + SQLite（默认）

## 快速开始
```bash
# 1) 创建并激活虚拟环境（Windows 示例）
python -m venv venv
venv\Scripts\activate

# 2) 安装依赖
pip install -r requirements.txt

# 3) 运行
python app.py
# 前台: http://127.0.0.1:5000
# 后台: http://127.0.0.1:5000/admin
```
首次启动会自动创建默认管理员账户（用户名和密码在 `.env` 文件中配置）。

## 环境变量配置
1. 复制 `.env.example` 为 `.env`：
```bash
cp .env.example .env
```

2. 编辑 `.env` 文件，配置以下变量：
```env
# 应用配置
SECRET_KEY=your-secret-key-change-in-production
FLASK_ENV=development
FLASK_DEBUG=True

# 数据库配置
DATABASE_URL=sqlite:///daigou.db

# 邮件配置
SMTP_SERVER=smtp.163.com
SMTP_PORT=465
SENDER_EMAIL=your-email@example.com
SENDER_PASSWORD=your-app-password
DEFAULT_RECEIVER_EMAIL=default-receiver@example.com

# 管理员账户配置
ADMIN_USERNAME=admin
ADMIN_PASSWORD=your-admin-password

# 文件上传配置
MAX_CONTENT_LENGTH=52428800
UPLOAD_FOLDER=static/uploads

# 时区配置
TIMEZONE=Asia/Shanghai
```

> 如需 MySQL/PostgreSQL：`DATABASE_URL=mysql+pymysql://user:pwd@host/dbname?charset=utf8mb4`

## 目录与数据
- 上传目录：`static/uploads/`（商品图/付款截图/二维码/封面）
- 数据库：`instance/daigou.db`

## 迁移到 Linux（要点）
- 使用 `Gunicorn + Nginx` + systemd 管理进程与 HTTPS
- `static/uploads/` 需写权限；Nginx 配置 `client_max_body_size 50m;`
- APScheduler 多进程时仅在一个进程启用或改用 cron

## Git 提交建议
忽略：`instance/`、`static/uploads/`、`.env`、`venv/`、`__pycache__/`。可附带 `.env.example` 说明变量。

如需 Docker/CI 或 Nginx/Gunicorn/systemd 模板，请告知目标环境。
