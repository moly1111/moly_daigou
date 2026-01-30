#!/bin/bash
# 部署脚本：拉代码、迁移、重启。在项目根目录执行：bash scripts/deploy.sh
# 需已配置 .env、虚拟环境，生产环境建议用 systemd 管理 Gunicorn，本脚本仅做拉取与迁移。

set -e
cd "$(dirname "$0")/.."

echo "拉取代码..."
git fetch origin
git pull origin main

echo "安装依赖..."
pip install -r requirements.txt

export FLASK_APP=app.py
if [ ! -d "migrations" ]; then
    echo "初始化迁移..."
    flask db init
fi
echo "生成并应用迁移..."
flask db migrate -m "Auto $(date +%Y%m%d_%H%M)" 2>/dev/null || true
flask db upgrade

echo "完成。请手动重启服务，例如：sudo systemctl restart moly-daigou"
