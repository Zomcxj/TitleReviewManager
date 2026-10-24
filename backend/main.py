import logging
import os
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text

from auth import get_current_user
from database import Base, engine
from routers import (
    applications,
    audit,
    auth,
    backup,
    batch,
    client_errors,
    customers,
    dashboard,
    exports,
    feedback,
    finance,
    follow_ups,
    imports,
    materials,
    notifications,
    public_pool,
    public_progress,
    recycle_bin,
    registration,
    reviews,
    system_config,
    users,
    word_import,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", handlers=[logging.StreamHandler()])
logger = logging.getLogger(__name__)

ALLOWED_ORIGINS = os.getenv("ALLOWED_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173,https://5173-e5215720889685e1.monkeycode-ai.online").split(",")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    """Application lifespan: on startup, run a read-only schema drift check and start the built-in scheduler.

    Schema authority is unified onto the single Alembic path: structural changes can only be made
    through migrations, and the startup hook no longer executes any DDL. Previously this hook ran
    create_all to create tables and auto-added missing columns/indexes, making it impossible to
    trace "who changed the DB structure" and masking defects in the migration chain itself
    (the initial migration once missed the applications.cycle_deadline index, long hidden by
    the auto-indexing).

    To create/upgrade the database use `python db_bootstrap.py` or `alembic upgrade head`;
    the Docker start command now uses the former. This hook only detects and warns, never
    modifying any structure.
    """
    try:
        from utils.schema_sync import log_drift
        log_drift(engine, Base)
    except Exception as e:
        logger.error(f"schema 漂移检测失败（不影响启动）: {e}", exc_info=True)

    # Start the built-in scheduler: SLA auto-reclaim/timeout reminders previously relied on an
    # external cron, which deployments easily miss, silently disabling the feature
    try:
        from utils.scheduler import start_scheduler
        start_scheduler()
    except Exception as e:
        logger.error(f"调度器启动失败（不影响启动）: {e}", exc_info=True)

    yield

    # Stop the scheduler thread on shutdown so it is not still running internally during graceful exit
    try:
        from utils.scheduler import stop_scheduler
        stop_scheduler()
    except Exception as e:
        logger.warning(f"停止调度器失败: {e}")


app = FastAPI(title="职称服务内部管理平台", version="1.0.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=ALLOWED_ORIGINS, allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

# Tamper-proof audit log: register the hash-chain hook (computes a chained hash automatically before any OperationLog is persisted)
try:
    from utils.audit_chain import register_chain_hook
    register_chain_hook()
except Exception as _e:
    logger.warning(f"审计哈希链钩子注册失败: {_e}")

# Security response headers (CSP / X-Frame-Options / nosniff etc.), see utils/security_headers.py
from utils.security_headers import HttpsRedirectMiddleware, SecurityHeadersMiddleware

app.add_middleware(SecurityHeadersMiddleware)
# Force HTTPS redirect (active when FORCE_HTTPS=1; health check paths exempt)
app.add_middleware(HttpsRedirectMiddleware)

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
app.include_router(backup.router)
app.include_router(client_errors.router)

# Note: the uploads directory is no longer mounted statically — review/feedback attachments must go
# through authenticated download endpoints, so sensitive customer files are not anonymously
# accessible (the old /uploads was fully public).

# Frontend build output directory: set FRONTEND_DIST for container deploys; local dev falls back to frontend/dist
frontend_dir = os.getenv("FRONTEND_DIST") or os.path.join(os.path.dirname(os.path.dirname(__file__)), "frontend", "dist")
if os.path.exists(frontend_dir):
    app.mount("/assets", StaticFiles(directory=os.path.join(frontend_dir, "assets")), name="frontend_assets")




@app.get("/api/health")
async def health():
    """Basic health check (for container HEALTHCHECK / external probes; no auth required).

    Exception details go to the log only, never back to the caller: this endpoint is externally
    reachable (external probes hit it), so returning raw database errors would leak
    infrastructure information to the public internet.
    """
    try:
        from database import SessionLocal
        db = SessionLocal()
        db.execute(text("SELECT 1"))
        db.close()
        return {"status": "ok", "database": "connected", "timestamp": datetime.now(timezone.utc).isoformat()}
    except Exception as e:
        logger.error(f"健康检查失败（数据库异常，详情见日志）: {e}", exc_info=True)
        return {"status": "error", "database": "unavailable", "timestamp": datetime.now(timezone.utc).isoformat()}


@app.get("/api/health/detail")
async def health_detail(current_user: dict = Depends(get_current_user)):
    """Detailed health and configuration self-check (for ops troubleshooting; no sensitive values).

    Requires admin login: this endpoint exposes infrastructure details such as JWT secret
    strength, storage paths and scheduler status, and the service has an externally reachable
    address (customer registration links) — anonymous access would hand reconnaissance intel
    to attackers. Log in as admin in the browser and visit it directly (cookie auth).

    The most common post-launch pitfall is "configuration silently not taking effect" — e.g. the
    JWT secret still being the default, an unwritable storage directory, or external
    notifications configured but unable to send. This check runs proactively and gives advice.
    """
    if current_user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="只有管理员可以查看配置自检")
    import os as _os

    from database import DATABASE_URL, SessionLocal

    checks = []

    # Database connectivity
    db_ok, db_msg = True, "连接正常"
    try:
        db = SessionLocal()
        db.execute(text("SELECT 1"))
        db_url = str(DATABASE_URL)
        # Mask the password in the connection string
        import re as _re
        db_url = _re.sub(r"://([^:]+):([^@]+)@", r"://\1:***@", db_url)
        db.close()
    except Exception as e:
        db_ok, db_msg, db_url = False, str(e), "(不可用)"
    checks.append({"name": "数据库", "ok": db_ok, "detail": db_msg, "extra": db_url})

    # Database type (PostgreSQL recommended for production)
    is_sqlite = str(DATABASE_URL).startswith("sqlite")
    checks.append({
        "name": "数据库类型",
        "ok": not is_sqlite,
        "detail": "SQLite（单机可用，多实例部署请改用 PostgreSQL）" if is_sqlite else "PostgreSQL",
    })

    # JWT secret strength
    secret = _os.getenv("JWT_SECRET_KEY", "")
    weak = (not secret) or len(secret) < 32 or secret.lower() in (
        "change-me-in-production", "secret", "your-super-secret-and-complex-key")
    checks.append({
        "name": "JWT 密钥",
        "ok": not weak,
        "detail": f"长度 {len(secret)}；建议 ≥32 位随机字符串" + ("（当前为默认/弱密钥，请立即更换）" if weak else ""),
    })

    # Storage directory writability
    try:
        from storage import get_storage_root
        root = get_storage_root()
        _os.makedirs(root, exist_ok=True)
        probe = _os.path.join(root, ".write_probe")
        with open(probe, "w") as f:
            f.write("ok")
        _os.remove(probe)
        checks.append({"name": "存储目录", "ok": True, "detail": "可读写", "extra": root})
    except Exception as e:
        checks.append({"name": "存储目录", "ok": False, "detail": f"不可写：{e}"})

    # External notification channels
    try:
        from utils.notify_channels import channel_status
        st = channel_status()
        email_ready = st["email"]["enabled"] and st["email"]["configured"]
        hook_ready = st["webhook"]["enabled"] and st["webhook"]["configured"]
        checks.append({
            "name": "外部通知",
            "ok": True,  # unconfigured is a normal state, not a failure
            "detail": ("邮件已启用；" if email_ready else "") + ("Webhook 已启用" if hook_ready else "")
                      + ("（均未配置，仅站内通知）" if not (email_ready or hook_ready) else ""),
        })
    except Exception as e:
        checks.append({"name": "外部通知", "ok": False, "detail": str(e)})

    # System config readability
    try:
        from utils.system_config import get_config
        db = SessionLocal()
        limit = get_config(db, "pool_claim_limit")
        db.close()
        checks.append({"name": "系统配置", "ok": True, "detail": f"可读取（公海限额 {limit}）"})
    except Exception as e:
        checks.append({"name": "系统配置", "ok": False, "detail": str(e)})

    # Scheduled task notice (SLA cron jobs must be triggered by an external cron)
    checks.append({
        "name": "SLA 定时任务",
        "ok": True,
        "detail": "需由外部计划任务调用 python tasks/sla_scheduler.py（建议每日一次）",
    })

    failed = [c for c in checks if not c["ok"]]
    return {
        "status": "ok" if not failed else "warning",
        "failed_count": len(failed),
        "checks": checks,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

@app.exception_handler(404)
async def not_found_handler(request: Request, exc: HTTPException):
    path = request.url.path
    if path.startswith("/api/") or path.startswith("/uploads/"):
        # Keep the original detail raised by business endpoints (e.g. "material not found"); only unknown paths fall back here
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


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    """Convert Pydantic validation errors into Chinese messages the frontend can display directly.

    The default 422 response body is a nested array (loc/msg/type), which renders poorly in the
    frontend ElMessage; here the first error is extracted and flattened into a string detail,
    while the full errors are kept for debugging.
    """
    errors = exc.errors()
    messages = []
    safe_errors = []
    for err in errors:
        msg = err.get("msg", "")
        # Pydantic v2 prefixes custom validator error messages with "Value error, "
        msg = msg.replace("Value error, ", "")
        loc = [str(x) for x in err.get("loc", []) if x not in ("body", "query", "path")]
        field = ".".join(loc)
        if field and msg:
            messages.append(f"{field}: {msg}")
        elif msg:
            messages.append(msg)
        # ctx may contain non-JSON-serializable objects such as ValueError; keep only the basic fields
        raw_input = err.get("input")
        safe_errors.append({
            "loc": loc,
            "msg": msg,
            "type": err.get("type", ""),
            "input": raw_input if isinstance(raw_input, (str, int, float, bool, type(None))) else None,
        })
    detail = "；".join(messages) if messages else "请求参数不合法"
    logger.info(f"参数校验失败 {request.url.path}: {detail}")
    return JSONResponse(status_code=422, content={"detail": detail, "errors": safe_errors})

@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    if exc.status_code >= 500:
        logger.error(f"HTTP error {exc.status_code}: {exc.detail}")
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})
