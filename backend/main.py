from fastapi import FastAPI, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse, FileResponse
from database import engine, Base
from sqlalchemy import text
from routers import auth, customers, applications, materials, reviews, feedback, registration, audit, exports, notifications, follow_ups, public_pool, batch, dashboard, users, imports, word_import, public_progress, finance, system_config, recycle_bin
import os, logging
from datetime import datetime, timezone

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", handlers=[logging.StreamHandler()])
logger = logging.getLogger(__name__)

ALLOWED_ORIGINS = os.getenv("ALLOWED_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173,https://5173-e5215720889685e1.monkeycode-ai.online").split(",")

app = FastAPI(title="职称服务内部管理平台", version="1.0.0")
app.add_middleware(CORSMiddleware, allow_origins=ALLOWED_ORIGINS, allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

app.include_router(auth.router)
app.include_router(customers.router)
app.include_router(applications.router)
app.include_router(materials.router)
app.include_router(reviews.router)
app.include_router(feedback.router)
app.include_router(registration.router)
app.include_router(audit.router)
app.include_router(exports.router)
app.include_router(notifications.router)
app.include_router(follow_ups.router)
app.include_router(public_pool.router)
app.include_router(batch.router)
app.include_router(dashboard.router)
app.include_router(users.router)
app.include_router(imports.router)
app.include_router(word_import.router)
app.include_router(public_progress.router)
app.include_router(finance.router)
app.include_router(system_config.router)
app.include_router(recycle_bin.router)

# 注意：uploads 目录不再静态挂载 —— 审核附件、反馈附件必须走鉴权下载接口，
# 避免客户敏感文件被匿名访问（原先 /uploads 是完全公开的）。

frontend_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "frontend", "dist")
if os.path.exists(frontend_dir):
    app.mount("/assets", StaticFiles(directory=os.path.join(frontend_dir, "assets")), name="frontend_assets")


@app.on_event("startup")
def ensure_tables():
    """建表兜底 + 轻量结构同步：保证已有库升级代码后直接可用（只加表/加列，不删改）。"""
    Base.metadata.create_all(bind=engine)
    try:
        from utils.schema_sync import sync_schema
        summary = sync_schema(engine, Base)
        if summary["created_tables"] or summary["added_columns"]:
            logger.info(f"schema 同步完成: 新表 {summary['created_tables']}, 新列 {len(summary['added_columns'])} 个")
    except Exception as e:
        logger.error(f"schema 同步失败（不影响启动）: {e}", exc_info=True)


@app.get("/api/health")
async def health():
    try:
        from database import SessionLocal
        db = SessionLocal()
        db.execute(text("SELECT 1"))
        db.close()
        return {"status": "ok", "database": "connected", "timestamp": datetime.now(timezone.utc).isoformat()}
    except Exception as e:
        return {"status": "error", "database": str(e), "timestamp": datetime.now(timezone.utc).isoformat()}

@app.exception_handler(404)
async def not_found_handler(request: Request, exc: HTTPException):
    path = request.url.path
    if path.startswith("/api/") or path.startswith("/uploads/"):
        # 保留业务端点抛出的原始 detail（如「材料不存在」），仅对未知路径兜底
        detail = getattr(exc, "detail", None) or "Not Found"
        return JSONResponse(status_code=404, content={"detail": detail})
    index = os.path.join(frontend_dir, "index.html")
    if os.path.exists(index):
        return FileResponse(index)
    return JSONResponse(status_code=404, content={"detail": "Not Found"})

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.error(f"Unhandled exception: {exc}", exc_info=True)
    return JSONResponse(status_code=500, content={"detail": "Internal server error", "type": type(exc).__name__})

@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    if exc.status_code >= 500:
        logger.error(f"HTTP error {exc.status_code}: {exc.detail}")
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})
