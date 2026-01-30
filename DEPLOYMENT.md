# 部署指南

本文档说明如何从零部署 Moly 代购网站（含 Docker、Gunicorn、Nginx、systemd），以及敏感信息与迁移注意事项。

---

## 一、环境变量与敏感信息

### 1. 必填环境变量

在项目根目录创建 `.env`（可复制 `.env.example` 后修改），**必须**填写：

- `SECRET_KEY`：应用密钥，请使用足够随机的长字符串（生产勿用默认占位）
- `ADMIN_USERNAME`：管理员登录用户名
- `ADMIN_PASSWORD`：管理员登录密码（应用内会做 hash 存储）

### 2. 敏感信息保护

以下内容仅放在 `.env` 或环境变量中，**不要**提交到 Git：

- 邮件配置（SMTP 服务器、邮箱、密码）
- 管理员账号与密码
- `SECRET_KEY`
- 数据库连接串（若使用 MySQL/PostgreSQL）
- `RFID_API_KEY`（RFID 入库接口密钥）

`.gitignore` 已包含 `.env`、`instance/`、`static/uploads/` 等，请勿移除。

### 3. 上传到 GitHub 前的检查

```bash
# 确认 .env 未被跟踪
git status
git check-ignore .env

# 提交时不要 add .env
git add .
git commit -m "你的提交说明"
git push
```

---

## 二、Docker 部署（推荐）

### 1. 使用 Docker Compose

```bash
# 1. 克隆项目
git clone https://github.com/yourusername/moly_daigou.git
cd moly_daigou

# 2. 配置环境变量
cp .env.example .env
# 编辑 .env，至少填写 SECRET_KEY、ADMIN_USERNAME、ADMIN_PASSWORD

# 3. 构建并启动
docker compose up -d --build

# 4. 首次运行：执行数据库迁移
docker compose exec moly_daigou flask db upgrade
```

- 访问：前台 http://localhost:5000 ，后台 http://localhost:5000/admin
- 数据与上传文件通过卷挂载持久化：
  - `./instance` → 数据库（SQLite 等）
  - `./static/uploads` → 上传文件

### 2. 仅使用 Dockerfile（不推荐新手）

```bash
docker build -t moly_daigou .
docker run -d -p 5000:5000 \
  -e SECRET_KEY=你的密钥 \
  -e ADMIN_USERNAME=admin \
  -e ADMIN_PASSWORD=你的密码 \
  -v $(pwd)/instance:/app/instance \
  -v $(pwd)/static/uploads:/app/static/uploads \
  --name moly_daigou moly_daigou
```

首次运行后进入容器执行：`docker exec moly_daigou flask db upgrade`

### 3. Docker 下使用 Gunicorn（生产）

若希望容器内用 Gunicorn 多 worker（不跑定时任务），可覆盖启动命令：

```yaml
# docker-compose.yml 中 services.moly_daigou 增加：
command: ["gunicorn", "-c", "gunicorn.conf.py", "wsgi:application"]
```

注意：使用 Gunicorn 且要跑定时任务时，需设置 `RUN_SCHEDULER=1` 且 `GUNICORN_WORKERS=1`（见项目 `gunicorn.conf.py` 与 `app.py`）。

---

## 三、非 Docker 部署（Linux 示例）

### 1. 快速运行（开发/自用）

```bash
git clone https://github.com/yourusername/moly_daigou.git
cd moly_daigou
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# 编辑 .env
flask db upgrade
python app.py
```

### 2. 生产环境：Gunicorn + Nginx

#### 环境变量（生产）

在 `.env` 或 systemd 中设置：

```env
FLASK_ENV=production
FLASK_DEBUG=False
# 使用 Gunicorn 且需要定时任务时：单 worker + 开启调度器
GUNICORN_WORKERS=1
RUN_SCHEDULER=1
```

若多 worker 且不跑定时任务，则不设置 `RUN_SCHEDULER`；定时逻辑可改为系统 cron 调用脚本。

#### 使用 Gunicorn 启动

```bash
pip install gunicorn
gunicorn -c gunicorn.conf.py wsgi:application

# 或指定绑定与 worker 数
GUNICORN_BIND=127.0.0.1:5000 GUNICORN_WORKERS=2 gunicorn -c gunicorn.conf.py wsgi:application
```

#### Nginx 反向代理

参考项目根目录 `deploy/nginx.conf.example`。要点：

- `client_max_body_size 50m;`（上传）
- `proxy_pass http://127.0.0.1:5000;`（与 Gunicorn 绑定一致）

#### systemd 服务

示例 `/etc/systemd/system/moly-daigou.service`：

```ini
[Unit]
Description=Moly Daigou Web
After=network.target

[Service]
User=www-data
WorkingDirectory=/path/to/moly_daigou
Environment="PATH=/path/to/moly_daigou/venv/bin"
ExecStart=/path/to/moly_daigou/venv/bin/gunicorn -c gunicorn.conf.py wsgi:application
Restart=always

[Install]
WantedBy=multi-user.target
```

然后：

```bash
sudo systemctl daemon-reload
sudo systemctl enable moly-daigou
sudo systemctl start moly-daigou
# 查看状态与日志
sudo systemctl status moly-daigou
journalctl -u moly-daigou -f
```

---

## 四、数据库迁移

- 使用 **Flask-Migrate**（Alembic）：`flask db init` → `flask db migrate -m "说明"` → `flask db upgrade`。
- 部署脚本：可选 `scripts/deploy.sh`（拉代码、安装依赖、执行迁移）；重启服务请用 systemd 或 Docker。
- 开发默认 SQLite；生产可改为 MySQL/PostgreSQL，在 `.env` 中设置 `DATABASE_URL` 即可。

---

## 五、定时任务说明

- **开发**：`python app.py` 会默认启动定时任务（自动取消未付款订单、清理验证码等）。
- **生产（Gunicorn）**：仅在设置 `RUN_SCHEDULER=1` 时在进程内启动；且需**单 worker**，否则会多进程重复执行。也可关闭 `RUN_SCHEDULER`，用系统 cron 定期执行对应逻辑（需自行编写脚本调用 `services.tasks` 中的函数）。

---

## 六、安全与运维建议

1. 生产环境必须修改默认的 `SECRET_KEY`，使用强随机值。
2. 管理员使用强密码，并定期更换。
3. 定期备份数据库（`instance/daigou.db` 或生产库）。
4. 配置防火墙，仅开放必要端口；对外使用 Nginx + HTTPS。
5. 使用 HTTPS 加密传输（Let’s Encrypt 等）。

---

## 七、故障排查

- **Docker**：`docker compose logs -f moly_daigou` 查看容器日志。
- **systemd**：`journalctl -u moly-daigou -f` 查看服务日志。
- **迁移失败**：确认 `DATABASE_URL` 与当前环境一致，必要时备份后重新执行 `flask db upgrade`。
- **上传/静态文件 404**：确认卷挂载或 Nginx 对 `static/uploads` 的配置正确。
