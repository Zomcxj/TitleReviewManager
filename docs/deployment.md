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
pip install -r requirements.txt

# 前端
cd frontend
npm install
```

### 3. 配置环境变量

```bash
# 复制示例文件并按需修改
cp .env.example .env
```

### 4. 初始化数据库 & 种子数据

```bash
cd backend

# 运行数据库迁移
alembic upgrade head

# 填充种子数据
python seed.py
```

默认创建 5 个用户、8 个客户、9 个申报批次（含示例材料）。

### 5. 启动服务

```bash
# 后端（端口 8000）
cd backend
uvicorn main:app --host 0.0.0.0 --port 8000 --reload

# 前端（端口 5173，另一个终端）
cd frontend
npm run dev
```

访问 http://localhost:5173，用 `admin / admin123` 登录。

---

## 生产环境

### 1. PostgreSQL 数据库

设置环境变量切换数据库（默认为 SQLite）：

```bash
export DATABASE_URL="postgresql://titleadmin:password@localhost:5432/titleservice"
```

首次启动会自动建表。生产环境建议手动建库：

```bash
createdb titleservice
```

### 2. 环境变量

```bash
export JWT_SECRET_KEY="your-strong-secret-key"
export ALLOWED_ORIGINS="https://yourdomain.com"
export STORAGE_BACKEND="local"       # 或 "smb"
export NAS_ROOT="/data/nas"          # 存储根目录
```

### 3. 前端构建

```bash
cd frontend
npm run build
# 构建产出在 frontend/dist/
```

将 `dist/` 部署到 Nginx，并配置反向代理到后端 `/api/`。

### 4. 后端启动（生产）

```bash
cd backend
pip install gunicorn
gunicorn main:app -w 4 -k uvicorn.workers.UvicornWorker --bind 0.0.0.0:8000
```

---

## Docker 部署

### 构建并启动

```bash
docker-compose up -d --build
```

### 服务组成

| 服务 | 端口 | 说明 |
|------|------|------|
| `db` | 5432 | PostgreSQL 15 |
| `backend` | 8000 | FastAPI + Uvicorn |
| `frontend` | 5173 | Vue 3 + Vite 开发服务器 |

### 环境变量（docker-compose）

编辑 `docker-compose.yml` 中的 `backend.environment`：

```yaml
environment:
  DATABASE_URL: postgresql://titleadmin:changeme@db:5432/titleservice
  JWT_SECRET_KEY: ${JWT_SECRET_KEY:-change-me-in-production}
  STORAGE_BACKEND: local
  NAS_ROOT: /data/nas
```

### 持久化数据

- PostgreSQL 数据：`pgdata` 命名 volume
- NAS 文件：`nas_data` 命名 volume（挂载到 `/data/nas`）

---

## 测试

```bash
# 后端 API 测试（自动启动/停止服务器）
cd tests
python test_storage.py
python test_users.py
```

---

## NAS 存储配置

### 目录模板

```
customers/{year}/{salesman_name}/{customer_name}_{pinyin}/{category_number}-{category_name}/{filename}
```

### 本地模式（默认）

```bash
export STORAGE_BACKEND=local
export NAS_ROOT=./nas_storage
```

### SMB 模式（Synology/QNAP）

```bash
export STORAGE_BACKEND=smb
export NAS_ROOT="//192.168.1.100/title_files"
export SMB_USER="nas_user"
export SMB_PASS="nas_password"
```

---

## Nginx 反向代理示例

```nginx
server {
    listen 80;
    server_name yourdomain.com;

    # 前端静态文件
    root /path/to/frontend/dist;
    index index.html;

    # API 代理
    location /api/ {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }

    # SPA 路由
    location / {
        try_files $uri $uri/ /index.html;
    }
}
```

---

## 默认账号

| 角色 | 用户名 | 密码 |
|------|--------|------|
| 管理员 | admin | admin123 |
| 业务员 | salesman1 | sales123 |
| 业务员 | salesman2 | sales123 |
| 审核员 | reviewer1 | review123 |
| 审核员 | reviewer2 | review123 |
