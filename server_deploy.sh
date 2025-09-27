#!/bin/bash
echo "🚀 服务器Flask-Migrate部署脚本"
echo "=================================="

# 检查是否在正确的目录
if [ ! -f "app.py" ]; then
    echo "❌ 错误：请在项目根目录运行此脚本"
    exit 1
fi

# 1. 停止所有Gunicorn进程
echo "⏹️ 停止Gunicorn服务..."
sudo pkill -9 -f gunicorn
sleep 3

# 2. 拉取最新代码
echo "📥 拉取最新代码..."
git fetch origin
git reset --hard origin/main

# 3. 安装/更新依赖
echo "📦 安装依赖..."
pip install -r requirements.txt

# 4. 设置Flask应用环境变量
export FLASK_APP=app.py
export FLASK_ENV=production

# 5. 初始化迁移（如果还没有）
if [ ! -d "migrations" ]; then
    echo "🔧 初始化Flask-Migrate..."
    flask db init
fi

# 6. 生成迁移文件
echo "📝 生成迁移文件..."
flask db migrate -m "Auto migration $(date +%Y%m%d_%H%M%S)"

# 7. 应用迁移
echo "🔄 应用数据库迁移..."
flask db upgrade

# 8. 启动Gunicorn
echo "🚀 启动Gunicorn服务..."
cd /opt/moly_daigou
source venv/bin/activate
nohup gunicorn --workers 1 --threads 8 --worker-class gthread --timeout 60 --keep-alive 5 --bind 0.0.0.0:8080 app:app > app.log 2>&1 &

# 9. 等待启动
echo "⏳ 等待服务启动..."
sleep 10

# 10. 测试服务
echo "🧪 测试服务..."
if curl -I http://localhost:8080/admin > /dev/null 2>&1; then
    echo "✅ 服务启动成功！"
    echo "🌐 前端: http://your-domain.com"
    echo "🔧 后端: http://your-domain.com:8080/admin"
else
    echo "❌ 服务启动失败，请检查日志:"
    echo "📊 查看日志: tail -f app.log"
    echo "🔍 检查进程: ps aux | grep gunicorn"
fi

echo "=================================="
echo "✅ 部署完成！"
