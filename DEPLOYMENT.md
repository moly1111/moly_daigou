# 部署指南

## GitHub 上传准备

### 1. 环境变量配置
- ✅ 已创建 `.env.example` 示例文件
- ✅ 已创建 `.env` 本地配置文件（包含真实配置）
- ✅ 已更新 `.gitignore` 忽略敏感文件
- ✅ 已修改代码使用环境变量

### 2. 敏感信息保护
以下信息已移至环境变量，不会上传到GitHub：
- 邮件配置（SMTP服务器、邮箱、密码）
- 管理员账户信息
- 应用密钥
- 数据库配置

### 3. 上传到GitHub步骤
```bash
# 1. 初始化Git仓库
git init

# 2. 添加所有文件（.env会被.gitignore忽略）
git add .

# 3. 提交
git commit -m "Initial commit: Moly代购网站"

# 4. 添加远程仓库
git remote add origin https://github.com/yourusername/your-repo-name.git

# 5. 推送到GitHub
git push -u origin main
```

### 4. 从GitHub部署
```bash
# 1. 克隆仓库
git clone https://github.com/yourusername/your-repo-name.git
cd your-repo-name

# 2. 创建虚拟环境
python -m venv venv
source venv/bin/activate  # Linux/Mac
# 或
venv\Scripts\activate     # Windows

# 3. 安装依赖
pip install -r requirements.txt

# 4. 配置环境变量
cp .env.example .env
# 编辑 .env 文件，填入真实配置

# 5. 运行应用
python app.py
```

## 生产环境部署建议

### Linux 服务器部署

### 快速部署（开发环境）
```bash
# 1. 克隆项目
git clone https://github.com/moly1111/moly_daigou.git
cd moly_daigou

# 2. 创建虚拟环境
python3 -m venv venv
source venv/bin/activate

# 3. 安装依赖
pip install -r requirements.txt

# 4. 配置环境变量
cp .env.example .env
nano .env  # 编辑配置文件

# 5. 运行应用
python app.py
```

### 生产环境部署
1. 使用 Gunicorn + Nginx
2. 配置 systemd 服务
3. 设置 HTTPS 证书
4. 配置防火墙规则

### Linux 兼容性确认
✅ 项目已使用跨平台路径处理（`os.path.join`）
✅ 使用标准库函数（`os.makedirs`）
✅ 配置为监听所有接口（`host='0.0.0.0'`）
✅ 使用环境变量配置，便于不同环境部署

### Docker 部署
可以创建 Dockerfile 和 docker-compose.yml 进行容器化部署

### 数据库迁移
- 开发环境：SQLite
- 生产环境：MySQL/PostgreSQL
- 修改 `.env` 中的 `DATABASE_URL` 即可

## 安全注意事项
1. 生产环境必须修改默认的 `SECRET_KEY`
2. 使用强密码作为管理员密码
3. 定期备份数据库
4. 配置防火墙限制访问
5. 使用 HTTPS 加密传输
