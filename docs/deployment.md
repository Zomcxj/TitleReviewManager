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


## 生产部署检查清单

上线前请逐项确认：

### 1. 必填配置（.env）

```bash
cp .env.example .env
# 至少设置以下三项，否则 compose 会拒绝启动：
#   JWT_SECRET_KEY       >= 32 位随机字符串（不要用示例值）
#   POSTGRES_PASSWORD    数据库强密码
#   ALLOWED_ORIGINS       你的实际域名
```

生成强密钥：`python -c "import secrets; print(secrets.token_urlsafe(48))"`

### 2. 启动

```bash
docker compose up -d --build
docker compose logs -f backend     # 观察迁移与调度器启动日志
```

容器启动时会自动执行 `alembic upgrade head`，无需手工迁移。

### 3. 上线自检

```bash
curl http://localhost:8000/api/health          # 基础探针
curl http://localhost:8000/api/health/detail   # 配置自检（会提示弱密钥/存储不可写等问题）
```

`/api/health/detail` 会检查：数据库连通性与类型、JWT 密钥强度、存储目录可写、
外部通知渠道、系统配置可读性、调度器状态。生产环境应全部为 `OK`。

### 4. 数据库迁移

```bash
docker compose exec backend alembic current    # 当前版本
docker compose exec backend alembic upgrade head
```

迁移使用 batch 模式兼容 SQLite；生产 PostgreSQL 为原生 ALTER。

> 注意：应用启动时还有一层 `schema_sync` 兜底（只加表/加列/加索引，绝不删改），
> 用于「代码已更新但忘记跑迁移」的场景。正式变更仍应生成 Alembic 迁移。

### 5. 定时任务

内置调度器默认开启（每 60 分钟执行 SLA 回收/超时提醒/临期提醒 + 清理过期登录记录）。
多 worker 场景下通过文件锁保证同一时刻只有一个 worker 执行。

若希望改用外部 cron：
```bash
# .env 中设置 SCHEDULER_ENABLED=0
0 2 * * * cd /app && python tasks/sla_scheduler.py
```

### 6. 数据备份

**已内置自动备份**（默认每天凌晨 3 点，随内置调度器执行）：

- 数据库：SQLite 用 sqlite3 backup API 做一致性快照后 gzip；PostgreSQL 用 pg_dump
- 材料文件：打包 `STORAGE_BACKEND` 指向的存储根目录为 tar.gz
- 每次备份写 `manifest_<时间戳>.json`（含类型/大小/文件数/结果）
- 默认保留最近 7 份，超出自动清理

配置（`.env`）：
```bash
BACKUP_ENABLED="1"          # 是否启用自动备份
BACKUP_DIR=""               # 默认 backend/backups
BACKUP_KEEP="7"             # 保留份数
BACKUP_HOUR="3"             # 每天几点执行（0-23）
BACKUP_INCLUDE_FILES="1"    # 是否一并备份材料文件
BACKUP_COMPRESS="1"         # 是否 gzip 压缩
```

管理员也可在界面「数据备份」页查看配置、手动触发、浏览历史备份。

#### 恢复步骤

```bash
# 1. 停止服务（避免恢复过程中仍有写入）
docker compose stop backend

# 2. 恢复数据库
#    SQLite：
gzip -dk db_<时间戳>.sqlite.gz
cp db_<时间戳>.sqlite <DATABASE_URL 指向的库文件>
#    PostgreSQL：
gzip -dk db_<时间戳>.sql.gz
psql -U titleadmin -d titleservice -f db_<时间戳>.sql

# 3. 恢复材料文件（解压到 storage.get_storage_root() 目录）
tar -xzf files_<时间戳>.tar.gz -C <存储根目录>

# 4. 重启并核对 manifest_<时间戳>.json
docker compose start backend
```

> PostgreSQL 环境需要容器内可执行 `pg_dump`（Dockerfile 已安装 postgresql-client）。
> 外部 cron 方式：`BACKUP_ENABLED=0` 关闭内置，改为 `python tasks/backup.py`。

### 7. 安全建议

- 默认种子账号（admin/admin123 等）**仅供开发**，生产环境请立即改密码或不要执行 `seed.py`
- 建议在反向代理（Nginx/Caddy）上启用 HTTPS，并设置 `PUBLIC_URL` 为 https 地址
- 数据库端口不要暴露到公网（compose 已默认不映射）
- 定期检查 `/api/audit` 中的「登录失败」记录
