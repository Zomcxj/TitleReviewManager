FROM node:20-alpine AS frontend-build
WORKDIR /web
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim AS runtime

WORKDIR /app

# psycopg2 需要 libpq；curl 用于 HEALTHCHECK
# postgresql-client 提供 pg_dump —— 生产用 PostgreSQL，自动备份靠它导出数据库。
# 不锁版本：pg_dump 只要不低于服务端大版本即可（服务端 postgres:15-alpine），
# 而 Debian 基础镜像升级时锁死版本反而会让构建失败。
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 curl postgresql-client && \
    rm -rf /var/lib/apt/lists/*

COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/ .
# 前端构建产物：FastAPI 托管 /assets 与 index.html（避免容器里跑 dev server）
COPY --from=frontend-build /web/dist /frontend_dist

ENV FRONTEND_DIST=/frontend_dist \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

EXPOSE 8000

# 构建期验证 pg_dump 可用：备份失败只会在凌晨 3 点发通知，等到那时才发现太晚。
# 让镜像构建直接失败，比让「备份静默失效」进入生产强得多。
RUN pg_dump --version

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD curl -fsS http://127.0.0.1:8000/api/health || exit 1

# 先执行数据库引导（Alembic 迁移，并兼容 create_all 建出的历史库）再启动；
# 多 worker 提升并发；proxy-headers 支持反向代理
CMD ["sh", "-c", "python db_bootstrap.py && exec uvicorn main:app --host 0.0.0.0 --port 8000 --workers ${WEB_CONCURRENCY:-4} --proxy-headers"]
