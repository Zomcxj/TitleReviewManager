FROM node:20-alpine AS frontend-build
WORKDIR /web
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.10-slim AS runtime

WORKDIR /app

# psycopg2 需要 libpq；curl 用于 HEALTHCHECK
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 curl && \
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

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD curl -fsS http://127.0.0.1:8000/api/health || exit 1

# 先执行数据库迁移再启动；多 worker 提升并发；proxy-headers 支持反向代理
CMD ["sh", "-c", "alembic upgrade head && exec uvicorn main:app --host 0.0.0.0 --port 8000 --workers ${WEB_CONCURRENCY:-4} --proxy-headers"]
