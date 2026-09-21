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
npm install
npm run build
# 构建产出在 frontend/dist/
```

将 `dist/` 部署到 Nginx，并配置反向代理到后端 `/api/`。

> `frontend/dist` **不纳入版本控制**（每次构建文件名带 hash，提交它只会产生大量
> 无意义的 diff）。因此克隆仓库后必须先构建前端；`start.bat` / `start.sh` 会在
> 检测到 dist 缺失或源码更新时自动构建，无需手工干预。

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
cd backend
python -m pytest          # 全部用例（使用临时库，不触碰开发库）

cd frontend
npm run test:run          # Vitest（跑一次即退出；裸 npm test 是 watch 模式）
npm run typecheck         # vue-tsc --noEmit
npm run lint              # ESLint（仅 error 级为门禁）
```

### 代码质量门禁

```bash
cd backend
ruff check .              # 规则集见 backend/ruff.toml
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

存储层只把 `NAS_ROOT` 当普通目录读写，**不实现 SMB 协议**，因此没有
`SMB_USER` / `SMB_PASS` —— 凭据由操作系统挂载负责。请先把共享挂载到本地路径，
再让应用指向该路径：

```bash
# 1) 先挂载共享（凭据在这里提供，不在应用配置里）
#    Linux: mount -t cifs //192.168.1.100/title_files /mnt/nas \
#             -o username=nas_user,password=***,vers=3.0
#    Windows: net use Z: \\192.168.1.100\title_files /user:nas_user ***

# 2) 应用指向挂载点
export STORAGE_BACKEND=smb
export NAS_ROOT="/mnt/nas"          # 或 Windows 下的 "Z:\\"
```

> Docker 部署时把该路径 bind mount 进容器，并让 `NAS_ROOT` 指向容器内路径，
> 例如 `-v /mnt/nas:/data/nas` 配合 `NAS_ROOT=/data/nas`（compose 已如此配置）。

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

> **schema 权威只有 Alembic 一条路径。** 应用启动时不再执行任何 DDL，
> 只做一次只读的漂移检测并在发现差异时打日志（`utils/schema_sync.py`）。
>
> 此前启动钩子会 `create_all` 建表并自动补列/补索引，导致「库结构是谁改的」
> 无法追溯，也掩盖了迁移链本身的缺陷（初始迁移曾漏建
> `applications.cycle_deadline` 索引，被自动补索引长期掩盖）。该兜底已移除。
>
> 若历史库是用 `create_all` 建出来的（本地 `start.bat` 路径，没有 alembic
> 版本记录），直接 `alembic upgrade head` 会报 `table already exists` 而失败。
> 用 `python db_bootstrap.py` 处理：它会先 `stamp head` 把现有结构标记为最新，
> 再执行迁移补齐差异。Docker 启动命令与两个启动脚本都已改为走这条路径。
>
> 注意 `stamp head` 意味着「现有结构已达最新」，因此这类库里若缺了后来新增的
> 列/索引，迁移链不会补。bootstrap 结束时会把差异打印出来；确认无误后可用
> `python db_bootstrap.py --repair` 显式补齐缺失的列与索引（只增不删，不动既有数据）。
> **默认不带 `--repair` 时全程只读** —— 不会在启动时静默改结构。

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
BACKUP_DIR=""               # 默认 backend/backups；docker compose 下默认 /data/backups
BACKUP_KEEP="7"             # 保留份数
BACKUP_HOUR="3"             # 每天几点执行（0-23）
BACKUP_INCLUDE_FILES="1"    # 是否一并备份材料文件
BACKUP_COMPRESS="1"         # 是否 gzip 压缩
```

> **Docker 部署注意**：`docker-compose.yml` 已把上述变量逐个转发给容器（compose 不使用
> `env_file`，`.env` 里的变量必须在 `environment` 段显式列出才生效），并把
> `backups_data` 卷挂到 `/data/backups`。**不要把 `BACKUP_DIR` 改到卷外**——备份放在
> 容器可写层里会随容器一起消失，失去备份的意义。想落到宿主机目录，改成 bind mount：
> ```yaml
>     volumes:
>       - /srv/trm-backups:/data/backups
> ```

管理员也可在界面「数据备份」页查看配置、手动触发、浏览历史备份。

#### 恢复步骤

推荐用内置的恢复工具（`backend/tasks/restore.py`），它会做校验并防止误覆盖：

```bash
cd backend

# 1. 查看有哪些备份
python tasks/restore.py --list

# 2. 校验备份完整性（gzip 可解、PRAGMA integrity_check、外键检查）
python tasks/restore.py --verify <时间戳>

# 3. 恢复演练：在临时位置完整走一遍恢复并校验数据可读
#    全程不接触生产库与生产材料目录 —— 先演练再恢复
python tasks/restore.py --drill <时间戳>

# 4. 真正恢复（会先停服务；默认拒绝覆盖已存在的库文件）
python tasks/restore.py --restore-db <时间戳>
python tasks/restore.py --restore-files <时间戳>
```

**每次备份成功后，调度器会自动做一次恢复演练**（`BACKUP_DRILL_ENABLED=0` 可关闭），
结果记在备份 manifest 的 `restore_drill` 字段 —— 备份是否真的可用不再靠假设。

手工恢复（无 Python 环境时）：

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

> SQLite 备份使用 `sqlite3.Connection.backup()` 做一致性快照，**不是**直接复制文件
> —— 后者在有写入时可能拷到损坏的库。
>
> 备份失败会向所有管理员发送站内通知（此前只写日志，等于失败被静默吞掉）。
>
> PostgreSQL 环境需要容器内可执行 `pg_dump`。官方 `Dockerfile` 已安装
> `postgresql-client`，并在构建期执行 `pg_dump --version` 做校验 —— 镜像里没有
> `pg_dump` 时构建会直接失败，而不是等到凌晨 3 点备份时才暴露。
> 自建镜像或非 Debian 基础镜像需自行安装（Alpine: `apk add postgresql-client`）。
>
> 外部 cron 方式：`BACKUP_ENABLED=0` 关闭内置，改为 `python tasks/backup.py`。

### 7. 安全建议

- 默认种子账号（admin/admin123 等）**仅供开发**，生产环境请立即改密码或不要执行 `seed.py`
- 建议在反向代理（Nginx/Caddy）上启用 HTTPS，并设置 `PUBLIC_URL` 为 https 地址
- 数据库端口不要暴露到公网（compose 已默认不映射）
- 定期检查 `/api/audit` 中的「登录失败」记录

### 8. HTTPS 与反向代理

生产环境务必走 HTTPS（内部系统的客户材料含身份证扫描件，明文传输不可接受）。

#### Nginx 参考配置

```nginx
server {
    listen 80;
    server_name your-domain.com;
    # 强制跳转 HTTPS
    return 301 https://$host$request_uri;
}

server {
    listen 443 ssl http2;
    server_name your-domain.com;

    ssl_certificate     /etc/nginx/ssl/fullchain.pem;
    ssl_certificate_key /etc/nginx/ssl/privkey.pem;
    ssl_protocols       TLSv1.2 TLSv1.3;

    client_max_body_size 60M;   # 材料上传上限 50MB，留出余量

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host              $host;
        proxy_set_header X-Real-IP         $remote_addr;
        # 应用据此解析真实客户端 IP（限流/审计/告警都依赖它）
        proxy_set_header X-Forwarded-For   $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

#### 对应的 .env 配置

```bash
TRUST_PROXY="1"      # 位于反代之后，采信 X-Forwarded-* 头
COOKIE_SECURE="1"    # cookie 仅走 https 传输
ENABLE_HSTS="1"      # 全站 HTTPS 确认可用后再开
FORCE_HTTPS="1"      # 应用层兜底跳转（代理已跳转可不开）
PUBLIC_URL="https://your-domain.com"
```

> **重要**：`TRUST_PROXY` 只在确实位于可信代理之后时才开。
> 单机直连部署保持 `0` —— 否则客户端可伪造 `X-Forwarded-For`
> 绕过登录限流与暴力破解检测。
>
> `COOKIE_SECURE=1` 后如果仍用 http 访问，浏览器不会发送 cookie，
> 表现为"登录成功但立刻又跳回登录页"。切换 https 时再开这一项。
>
> docker compose 部署时这四项同样需要在 `.env` 中设置：compose 已在
> `environment` 段转发 `TRUST_PROXY` / `FORCE_HTTPS` / `COOKIE_SECURE` /
> `ENABLE_HSTS`（默认均为 `0`，即直连安全默认值）。

### 9. 依赖漏洞扫描（CI）

`.github/workflows/security.yml` 已配置，包含五个任务：

| 任务 | 内容 |
|------|------|
| backend-security | `pip-audit` 扫依赖 CVE + `bandit` 静态安全分析 + `ruff check` |
| frontend-security | `npm audit`（high/critical 失败）+ `eslint src --quiet` + `vue-tsc` 类型检查 + `vitest run` + `vite build` |
| backend-tests | pytest（Python 3.10 与 3.12 双版本矩阵；3.12 额外跑废弃告警门禁） |
| migration-check | 从零执行全部迁移并校验表完整性；另测 create_all 历史库的接管路径 |
| docker-build | 真实构建镜像 + 容器内验证 `pg_dump` 可用 + 起容器确认 `/api/health` 返回 200 |

> 前端这一步此前只做依赖扫描与 eslint —— 而 eslint 不做类型检查，仓库里已有的
> vitest 用例也从不执行。现在类型检查、单元测试、生产构建都纳入门禁，
> 保证「能构建、类型对、测试过」在合并前就成立。
>
> `docker-build` 的存在理由：开发机通常不装 Docker，镜像能否构建、容器内该有的
> 工具在不在，只能在 CI 验证。`pg_dump` 缺失曾导致 PostgreSQL 自动备份永远失败，
> 且只在凌晨 3 点发一条站内通知才暴露 —— 现在构建期与 CI 双重拦截。

触发时机：push / PR 到 main、每周一自动扫描、可手动触发。

本地手动跑：

```bash
cd backend
pip install pip-audit bandit ruff
pip-audit -r requirements.txt --desc on
bandit -r . -ll -x tests,alembic --skip B101,B603,B607
ruff check .
```
