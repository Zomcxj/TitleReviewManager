# 部署指南

## 开发环境

### 1. 克隆仓库

```bash
git clone https://github.com/Zomcxj/TitleReviewManager.git
cd TitleReviewManager
```

### 2. 安装依赖

```bash
# 后端
cd backend
pip3 install -r requirements.txt --break-system-packages

# 前端
cd frontend
npm install
```

### 3. 启动服务

```bash
# 后端（端口 8000）
cd backend
python3 -m uvicorn main:app --host 0.0.0.0 --port 8000

# 前端（端口 5173）
cd frontend
npm run dev
```

## 生产环境

### 1. 数据库

使用 PostgreSQL 替换 SQLite：

```bash
export DATABASE_URL="postgresql://user:pass@localhost/dbname"
```

### 2. 环境变量

```bash
export ALLOWED_ORIGINS="https://yourdomain.com"
export JWT_SECRET_KEY="your-secret-key"
```

### 3. 前端构建

```bash
cd frontend
npm run build
```

### 4. 后端启动

```bash
cd backend
pip3 install gunicorn --break-system-packages
gunicorn main:app -w 4 -k uvicorn.workers.UvicornWorker --bind 0.0.0.0:8000
```

## 模拟数据

生成测试数据：

```bash
cd backend
python3 << 'EOF'
from database import engine, SessionLocal
from models import Base, User, Customer, Application, OperationLog
from datetime import datetime, timezone, timedelta
import random

Base.metadata.create_all(bind=engine)
db = SessionLocal()

# 创建用户、客户、申请、日志...
# （参考初始化脚本）

db.close()
print("完成")
EOF
```

## 自动化测试

```bash
cd tests
pip3 install pytest playwright --break-system-packages
playwright install
python3 phase2_test.py
python3 phase34_test.py
```
