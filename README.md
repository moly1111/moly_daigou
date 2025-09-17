## Moly 代购网站（单机/自用版）

一个面向个人的小型代购系统：支持多规格商品、变体图片与价格、购物车和订单、收款核验、聊天、基础仪表盘。默认 SQLite，适合 Windows 本地部署，也可迁移至 Linux。

### 核心功能
- 前台：
  - 访客可直接浏览商品（封面可关闭）
  - 注册/登录（邮箱验证码）与唯一收货地址
  - 商品多图展示，规格（尺寸/颜色等）选择并联动价格与图片
  - 购物车数量≥1、实时小计、下架项自动不计
  - 提交/取消订单，订单详情、付款截图上传
  - 深浅主题与图片放大（缩略图可禁放大）
- 后台：
  - 管理员登录（仅允许环境变量指定的账号）
  - 商品管理：多图、变体（名称/展示价/购入价/变体图）、置顶、删除
  - 订单管理：筛选/创建/标记收款（支持输入实收金额）/导出采购清单
  - 用户管理：直接创建用户（免邮箱验证）、封禁/解封/编辑/删除
  - 仪表盘：总收入、待收款、当日新单/营收、未读消息、热销 Top5
  - 基础设置：站点标题/页脚/封面上传
- 聊天：
  - 用户与管理员双向聊天
  - 支持文字、图片与通用文件（txt/docx/pdf/csv 等）
  - 轮询实时更新、在聊天页抑制重复通知、自动滚动到底部
- 定时任务：
  - 自动取消超时未付款订单
  - 清理过期邮箱验证码

### 技术栈
Flask + SQLAlchemy + Flask-Login + Bootstrap 5 + SQLite（默认）

## 快速开始（Windows 示例）
```bash
# 1) 创建并激活虚拟环境
python -m venv venv
venv\Scripts\activate

# 2) 安装依赖
pip install -r requirements.txt

# 3) 配置环境变量（必须）
# 新建 .env 并填写下方“环境变量”章节中的必填项

# 4) 启动
python app.py
# 前台: http://127.0.0.1:5000
# 后台: http://127.0.0.1:5000/admin
```

首次启动将：
- 校验必须的环境变量，缺失或默认占位将直接退出；
- 用 `ADMIN_USERNAME/ADMIN_PASSWORD` 初始化或更新管理员账户；
- 对旧 SQLite 库执行必要的列新增（见“自动迁移”）。

## 环境变量（必填/可选）
在项目根目录创建 `.env`：
```env
# 必填：安全/账号
SECRET_KEY=请填入足够随机的长字符串
ADMIN_USERNAME=你的管理员用户名
ADMIN_PASSWORD=你的强密码

# 可选：运行/数据库
FLASK_ENV=development
FLASK_DEBUG=True
DATABASE_URL=sqlite:///daigou.db
TIMEZONE=Asia/Shanghai

# 可选：邮件（用于注册验证码/通知）
SMTP_SERVER=smtp.163.com
SMTP_PORT=465
SENDER_EMAIL=your-email@example.com
SENDER_PASSWORD=your-app-password
DEFAULT_RECEIVER_EMAIL=default-receiver@example.com

# 可选：上传
MAX_CONTENT_LENGTH=52428800
UPLOAD_FOLDER=static/uploads
```

说明：
- 强制校验：`SECRET_KEY`、`ADMIN_USERNAME`、`ADMIN_PASSWORD` 必须通过环境变量注入，否则应用启动失败。
- 管理员登录：仅允许 `ADMIN_USERNAME` 指定的账号登录，历史账号（如 `admin`）即使存在也不可登录。
- 数据库默认 SQLite，便于单机部署；如需 MySQL/PostgreSQL，自行设置 `DATABASE_URL`。

## 数据与目录
- 数据库：`instance/daigou.db`
- 上传：`static/uploads/`（商品、支付截图、聊天文件、封面、二维码）

## 自动迁移（SQLite：应用启动时）
为兼容旧库，应用会在启动时按需新增缺失列（若已存在则跳过）：
- Product：`cost_price_rmb`、`variants`、`pinned`
- CartItem：`variant_name`
- OrderItem：`unit_price`、`unit_cost`、`variant_name`

并保持历史订单“价格不回溯”：下单时把单价/成本固化到 `OrderItem.unit_price/unit_cost`，之后改商品价不影响已下单统计。

## 功能要点与变化
- 商品变体：每个规格独立的名称、展示价、购入价与图片；商品顶层展示“¥最低规格价 起”。
- 商品统计：
  - 列表页展示：总销量、总下单数、总利润，支持“置顶”。
  - 详情页：分变体的销量、订单数、单规格利润、总利润。
- 订单金额：支持“应收/实收”拆分；标记收款时可输入实收金额。
- 聊天：支持通用文件上传，展示可下载链接；在聊天页时不弹重复通知，滚动跟随。
- 前端细节：
  - 商品详情：去除轮播，主图 + 缩略图；选规格联动主图与价格；缩略图禁缩放。
  - 暗色模式：图标与阴影适配，按钮可见性修复。
- 后台便捷：可直接创建用户（免邮箱验证），并可编辑其地址信息。

## 迁移到 Linux（简要）
- 推荐 `Gunicorn + Nginx + systemd`；Nginx 配置 `client_max_body_size 50m;`
- 确保 `static/uploads/` 写权限；APScheduler 建议单进程启用或改为系统级 cron

## Git/版本建议
- 忽略：`instance/`、`static/uploads/`、`.env`、`venv/`、`__pycache__`
- 保留 `.env.example` 列出变量示例（不含敏感值）

如需 Dockerfile、Nginx/Gunicorn 配置或 CI 模板，请告知目标环境与需求。


