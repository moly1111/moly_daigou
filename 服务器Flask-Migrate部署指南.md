# 🚀 服务器Flask-Migrate部署指南

## 📋 **部署步骤**

### **步骤1: 上传文件到服务器**
```bash
# 在本地提交代码到GitHub
git add .
git commit -m "添加Flask-Migrate支持"
git push origin main
```

### **步骤2: 在服务器上执行部署**
```bash
# 进入项目目录
cd /opt/moly_daigou

# 给脚本执行权限
chmod +x server_deploy.sh

# 执行部署
./server_deploy.sh
```

## 🔧 **Flask-Migrate 工作原理**

### **1. 初始化迁移**
```bash
# 首次使用需要初始化
flask db init
```

### **2. 生成迁移文件**
```bash
# 检测模型变化并生成迁移文件
flask db migrate -m "描述变化"
```

### **3. 应用迁移**
```bash
# 将迁移应用到数据库
flask db upgrade
```

## 🛠️ **手动操作步骤**

如果自动脚本失败，可以手动执行：

### **1. 停止服务**
```bash
sudo pkill -9 -f gunicorn
```

### **2. 拉取代码**
```bash
git pull origin main
```

### **3. 安装依赖**
```bash
pip install -r requirements.txt
```

### **4. 设置环境变量**
```bash
export FLASK_APP=app.py
export FLASK_ENV=production
```

### **5. 初始化迁移（仅首次）**
```bash
flask db init
```

### **6. 生成迁移**
```bash
flask db migrate -m "添加username和notes列"
```

### **7. 应用迁移**
```bash
flask db upgrade
```

### **8. 启动服务**
```bash
cd /opt/moly_daigou
source venv/bin/activate
nohup gunicorn --workers 1 --threads 8 --worker-class gthread --timeout 60 --keep-alive 5 --bind 0.0.0.0:8080 app:app > app.log 2>&1 &
```

## 🔍 **故障排除**

### **问题1: 迁移失败**
```bash
# 查看迁移状态
flask db current

# 查看迁移历史
flask db history

# 回滚到上一个版本
flask db downgrade
```

### **问题2: 数据库连接问题**
```bash
# 检查数据库连接
python3 -c "
from app import app, db
with app.app_context():
    try:
        db.session.execute(db.text('SELECT 1'))
        print('数据库连接正常')
    except Exception as e:
        print(f'数据库连接失败: {e}')
"
```

### **问题3: 服务启动失败**
```bash
# 查看日志
tail -f app.log

# 检查进程
ps aux | grep gunicorn

# 检查端口
ss -tlnp | grep :8080
```

## 📊 **迁移文件说明**

Flask-Migrate会在 `migrations/versions/` 目录下生成迁移文件，例如：
- `001_initial_migration.py` - 初始迁移
- `002_add_username_column.py` - 添加username列
- `003_add_notes_column.py` - 添加notes列

## 🎯 **优势**

### **✅ 解决的问题**
1. **自动数据库迁移** - 无需手动执行SQL
2. **版本控制** - 每个数据库变化都有记录
3. **回滚支持** - 可以回滚到之前的版本
4. **团队协作** - 多人开发时数据库结构同步
5. **生产环境安全** - 避免手动修改数据库

### **🔄 工作流程**
1. 修改模型代码
2. 生成迁移文件：`flask db migrate`
3. 应用迁移：`flask db upgrade`
4. 部署到生产环境

## 🚨 **注意事项**

1. **备份数据库** - 在生产环境应用迁移前先备份
2. **测试迁移** - 在测试环境先验证迁移
3. **检查迁移文件** - 确认生成的迁移文件正确
4. **监控日志** - 部署后检查应用日志

## 📞 **如果遇到问题**

1. 查看 `app.log` 日志文件
2. 检查数据库连接
3. 验证迁移文件是否正确
4. 必要时可以回滚迁移

---

**现在你的项目已经支持Flask-Migrate了！** 🎉

每次代码更新后，只需要运行 `./server_deploy.sh` 就能自动处理数据库迁移。
