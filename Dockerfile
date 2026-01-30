# Moly 代购网站 - 生产/开发均可使用
# 构建：docker build -t moly_daigou .
# 运行：见 docker-compose.yml；单独运行需挂载 instance 与 static/uploads，并传入环境变量

FROM python:3.12-slim

WORKDIR /app

# 系统依赖（编译部分 Python 包可能用到）
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Python 依赖
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 项目文件
COPY . .

# 便于在容器内执行 flask 命令
ENV FLASK_APP=app.py

EXPOSE 5000

# 默认使用 python app.py；生产可用 docker compose 或 Docker run 覆盖为 gunicorn
CMD ["python", "app.py"]
