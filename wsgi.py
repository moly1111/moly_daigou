# Gunicorn / uWSGI 入口：生产环境使用
# 启动示例：gunicorn -c gunicorn.conf.py wsgi:application
from app import app

application = app
