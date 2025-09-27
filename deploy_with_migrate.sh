#!/bin/bash
echo "🚀 开始Flask-Migrate部署..."

# 1. 停止服务
echo "⏹️ 停止Gunicorn服务..."
sudo pkill -9 -f gunicorn
sleep 5

# 2. 拉取代码
echo "📥 拉取最新代码..."
git pull origin main

# 3. 安装依赖
echo "📦 安装依赖..."
pip install -r requirements.txt

# 4. 初始化Flask-Migrate（如果还没有）
echo "🔧 初始化Flask-Migrate..."
if [ ! -d "migrations" ]; then
    echo "初始化迁移目录..."
    flask db init
fi

# 5. 生成迁移文件
echo "📝 生成迁移文件..."
flask db migrate -m "Auto migration $(date +%Y%m%d_%H%M%S)"

# 6. 应用迁移
echo "🔄 应用数据库迁移..."
flask db upgrade

# 7. 重启服务
echo "🚀 启动Gunicorn服务..."
cd /opt/moly_daigou
source venv/bin/activate
nohup gunicorn --workers 1 --threads 8 --worker-class gthread --timeout 60 --keep-alive 5 --bind 0.0.0.0:8080 app:app > app.log 2>&1 &

# 8. 等待启动
echo "⏳ 等待服务启动..."
sleep 10

# 9. 测试
echo "🧪 测试服务..."
curl -I http://localhost:8080/admin

echo "✅ Flask-Migrate部署完成！"
echo "📊 查看日志: tail -f app.log"
echo "🔍 检查进程: ps aux | grep gunicorn"
