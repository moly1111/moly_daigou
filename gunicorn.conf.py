# Gunicorn 生产配置
# 启动：gunicorn -c gunicorn.conf.py wsgi:application
import os

bind = os.getenv("GUNICORN_BIND", "0.0.0.0:5000")
workers = int(os.getenv("GUNICORN_WORKERS", "1"))  # 定时任务需单 worker 时设 RUN_SCHEDULER=1
threads = int(os.getenv("GUNICORN_THREADS", "4"))
worker_class = "sync"
worker_tmp_dir = "/dev/shm"  # 可选：Linux 下用内存盘
max_requests = 1000
max_requests_jitter = 50
timeout = 120
keepalive = 2
capture_output = True
enable_stdio_inheritance = True

# 生产务必关闭 debug
def on_starting(server):
    if os.getenv("FLASK_DEBUG", "").lower() in ("1", "true", "yes"):
        import logging
        logging.getLogger().warning("FLASK_DEBUG 已开启，生产环境请关闭")
