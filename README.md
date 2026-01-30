# Moly 代购网站

面向个人的小型代购系统：多规格商品与库存、购物车与订单、收款与发货、聊天、后台管理与仓储可视化。默认 SQLite，支持 Docker 一键运行。

## 功能概览

### 前台
- 商品浏览（多图、多规格、规格库存与价格联动）
- 注册/登录（邮箱验证码）、收货地址
- 购物车、下单、取消订单、付款截图上传
- 订单详情、发货通知（含快递号）
- 深浅主题、图片放大

### 后台
- 管理员登录（环境变量指定账号）
- **商品管理**：多图、规格（名称/展示价/购入价/库存/规格图）、置顶、删除
- **订单管理**：筛选、创建、标记收款、修改状态、导出发货清单
- **发货清单**：待发货按批次聚合（同日期同用户）、填快递号标记发货、已发货列表、邮件通知客户
- **用户管理**：创建用户、封禁/解封、编辑、删除
- **仓储可视化**：按商品/规格查看库存；**趋势**：近 1/7/30 天销量 Top 10 与柱状图
- **数据库**：只读查看所有表
- 仪表盘、基础设置、版本管理

### 其他
- **聊天**：用户与管理员双向聊天（文字、图片、文件）
- **定时任务**：自动取消超时未付款订单、清理过期验证码
- **RFID 入库 API**：`POST /api/rfid/ingest`，支持「商品id;规格id;数量」或「商品id;L:逻辑规格编号;数量」，用于硬件/模拟入库

## 技术栈

Flask + SQLAlchemy + Flask-Login + Flask-Migrate + Bootstrap 5 + SQLite（默认）

## 项目结构

```
moly_daigou/
├── app.py                 # 应用入口
├── wsgi.py                # Gunicorn 入口
├── gunicorn.conf.py       # Gunicorn 配置
├── core/                  # 核心：扩展、模型、工具
├── blueprints/            # 路由：frontend, admin_bp, chat, api_rfid
├── services/              # 邮件、定时任务
├── templates/             # Jinja2 模板
├── migrations/            # Flask-Migrate 迁移
├── simulate_hardware/     # RFID 入库模拟脚本与说明
├── deploy/                # 部署示例（如 nginx.conf.example）
├── scripts/               # 可选脚本（如 deploy.sh）
├── requirements.txt
├── Dockerfile
├── docker-compose.yml
├── README.md
└── DEPLOYMENT.md          # 部署与运维说明
```

## 快速开始

### 方式一：Docker（推荐）

```bash
# 1. 克隆项目
git clone https://github.com/yourusername/moly_daigou.git
cd moly_daigou

# 2. 配置环境变量
cp .env.example .env
# 编辑 .env，至少填写：SECRET_KEY、ADMIN_USERNAME、ADMIN_PASSWORD

# 3. 构建并启动
docker compose up -d --build

# 4. 首次运行执行数据库迁移
docker compose exec moly_daigou flask db upgrade
```

访问：前台 http://localhost:5000 ，后台 http://localhost:5000/admin

数据与上传文件会持久化在 `./instance` 与 `./static/uploads`（见 docker-compose 卷挂载）。

### 方式二：本地 Python

```bash
# 1. 虚拟环境
python3 -m venv venv
source venv/bin/activate   # Linux/macOS
# 或 venv\Scripts\activate  # Windows

# 2. 依赖
pip install -r requirements.txt

# 3. 环境变量（必填）
cp .env.example .env
# 编辑 .env：SECRET_KEY、ADMIN_USERNAME、ADMIN_PASSWORD

# 4. 迁移
flask db upgrade

# 5. 启动
python app.py
```

## 环境变量

在项目根目录创建 `.env`（参考 `.env.example`）：

| 变量 | 必填 | 说明 |
|------|------|------|
| `SECRET_KEY` | 是 | 应用密钥，请使用足够随机的长字符串 |
| `ADMIN_USERNAME` | 是 | 管理员登录用户名 |
| `ADMIN_PASSWORD` | 是 | 管理员登录密码（将做 hash 存储） |
| `DATABASE_URL` | 否 | 数据库 URL，默认 `sqlite:///daigou.db` |
| `FLASK_DEBUG` / `FLASK_ENV` | 否 | 开发时可设为 `1` / `development` |
| `UPLOAD_FOLDER` | 否 | 上传目录，默认 `static/uploads` |
| `MAX_CONTENT_LENGTH` | 否 | 上传大小限制（字节），默认约 50MB |
| `SMTP_*` / `SENDER_*` | 否 | 邮件配置（验证码、通知） |
| `RFID_API_KEY` | 否 | RFID 入库 API 密钥，不配置则接口返回 401 |

说明：管理员仅允许 `ADMIN_USERNAME` 对应的账号登录；RFID 接口鉴权使用 Header `X-API-Key` 或 query `api_key`。

## 数据与目录

- **数据库**：默认 `instance/daigou.db`（SQLite）
- **上传文件**：`static/uploads/`（商品图、支付截图、聊天文件、封面、二维码等）

## 数据库迁移

使用 Flask-Migrate（Alembic）：

```bash
flask db upgrade          # 应用迁移
flask db migrate -m "说明" # 生成新迁移（改模型后）
```

Docker 下：`docker compose exec moly_daigou flask db upgrade`

## 仓储与 RFID 入库

- **后台**：仓储可视化页可查看库存、销量趋势与柱状图；规格使用「逻辑编号」（按商品从 1 开始）。
- **API**：`POST /api/rfid/ingest`，Body 示例 `{"data": "2;L:1;3"}` 表示商品 2 的规格 1 入库 3 件。详见 `simulate_hardware/README.md` 与接口注释。

## 生产部署

- **进程**：建议 Gunicorn（见 `wsgi.py`、`gunicorn.conf.py`），配合 Nginx 反向代理。
- **定时任务**：生产环境通过环境变量 `RUN_SCHEDULER=1` 且单 worker 时在进程内执行；也可关闭后改用系统 cron。
- **HTTPS**：生产务必使用 HTTPS；SECRET_KEY、管理员密码需强随机且不提交仓库。

详见 **DEPLOYMENT.md**（含 Gunicorn、Nginx、systemd、Docker 说明）。

## 版本与忽略

- **Git**：建议忽略 `instance/`、`static/uploads/`、`.env`、`venv/`、`__pycache__`；保留 `.env.example` 作示例。
- **License**：按项目约定。
