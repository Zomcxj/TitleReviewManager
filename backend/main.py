from fastapi import FastAPI, Request, HTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse, FileResponse
from database import engine, Base
from sqlalchemy import text
from routers import auth, customers, applications, materials, reviews, feedback, registration, audit, exports, notifications, follow_ups, public_pool, batch, dashboard, users, imports, word_import, public_progress, finance, system_config, recycle_bin, backup, client_errors
import os, logging
from datetime import datetime, timezone

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", handlers=[logging.StreamHandler()])
logger = logging.getLogger(__name__)

ALLOWED_ORIGINS = os.getenv("ALLOWED_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173,https://5173-e5215720889685e1.monkeycode-ai.online").split(",")

app = FastAPI(title="职称服务内部管理平台", version="1.0.0")
app.add_middleware(CORSMiddleware, allow_origins=ALLOWED_ORIGINS, allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

# 审计日志防篡改：注册哈希链钩子（任何 OperationLog 落库前自动计算链式哈希）
try:
    from utils.audit_chain import register_chain_hook
    register_chain_hook()
except Exception as _e:
    logger.warning(f"审计哈希链钩子注册失败: {_e}")

# 安全响应头（CSP / X-Frame-Options / nosniff 等），详见 utils/security_headers.py
from utils.security_headers import SecurityHeadersMiddleware, HttpsRedirectMiddleware
app.add_middleware(SecurityHeadersMiddleware)
# 强制 HTTPS 跳转（FORCE_HTTPS=1 时生效；健康检查路径豁免）
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

# 注意：uploads 目录不再静态挂载 —— 审核附件、反馈附件必须走鉴权下载接口，
# 避免客户敏感文件被匿名访问（原先 /uploads 是完全公开的）。

# 前端构建产物目录：容器部署用 FRONTEND_DIST 指定，本地开发回落到 frontend/dist
frontend_dir = os.getenv("FRONTEND_DIST") or os.path.join(os.path.dirname(os.path.dirname(__file__)), "frontend", "dist")
if os.path.exists(frontend_dir):
    app.mount("/assets", StaticFiles(directory=os.path.join(frontend_dir, "assets")), name="frontend_assets")


@app.on_event("startup")
def ensure_tables():
    """建表兜底 + 轻量结构同步。

    Alembic 负责正式迁移（容器启动时执行 alembic upgrade head）；
    这里保证：
    1) 全新环境即使忘记跑迁移也能直接启动（create_all 建缺失表）
    2) 已有库升级代码后自动补齐新增列（只加表/加列，不删改）
    """
    Base.metadata.create_all(bind=engine)
    try:
        from utils.schema_sync import sync_schema
        summary = sync_schema(engine, Base)
        if summary["created_tables"] or summary["added_columns"] or summary.get("created_indexes"):
            logger.info(
                f"schema 同步完成: 新表 {summary['created_tables']}, "
                f"新列 {len(summary['added_columns'])} 个, 新索引 {len(summary.get('created_indexes', []))} 个"
            )
    except Exception as e:
        logger.error(f"schema 同步失败（不影响启动）: {e}", exc_info=True)

    # 启动内置调度器：SLA 自动回收/超时提醒此前依赖外部 cron，部署时极易遗漏导致功能静默失效
    try:
        from utils.scheduler import start_scheduler
        start_scheduler()
    except Exception as e:
        logger.error(f"调度器启动失败（不影响启动）: {e}", exc_info=True)


@app.get("/api/health")
async def health():
    """基础健康检查（供容器 HEALTHCHECK / 负载均衡探针使用，无需鉴权）"""
    try:
        from database import SessionLocal
        db = SessionLocal()
        db.execute(text("SELECT 1"))
        db.close()
        return {"status": "ok", "database": "connected", "timestamp": datetime.now(timezone.utc).isoformat()}
    except Exception as e:
        return {"status": "error", "database": str(e), "timestamp": datetime.now(timezone.utc).isoformat()}


@app.get("/api/health/detail")
async def health_detail():
    """详细健康与配置自检（供运维排查，不含敏感值）。

    上线后最常踩的坑是「配置没生效却不知道」——比如 JWT 密钥用的是默认值、
    存储目录不可写、外部通知配了但发不出去。这里主动做一次自检并给出建议。
    """
    from database import SessionLocal, DATABASE_URL
    import os as _os

    checks = []

    # 数据库连通性
    db_ok, db_msg = True, "连接正常"
    try:
        db = SessionLocal()
        db.execute(text("SELECT 1"))
        db_url = str(DATABASE_URL)
        # 隐藏连接串中的密码
        import re as _re
        db_url = _re.sub(r"://([^:]+):([^@]+)@", r"://\1:***@", db_url)
        db.close()
    except Exception as e:
        db_ok, db_msg, db_url = False, str(e), "(不可用)"
    checks.append({"name": "数据库", "ok": db_ok, "detail": db_msg, "extra": db_url})

    # 数据库类型（生产建议 PostgreSQL）
    is_sqlite = str(DATABASE_URL).startswith("sqlite")
    checks.append({
        "name": "数据库类型",
        "ok": not is_sqlite,
        "detail": "SQLite（单机可用，多实例部署请改用 PostgreSQL）" if is_sqlite else "PostgreSQL",
    })

    # JWT 密钥强度
    secret = _os.getenv("JWT_SECRET_KEY", "")
    weak = (not secret) or len(secret) < 32 or secret.lower() in (
        "change-me-in-production", "secret", "your-super-secret-and-complex-key")
    checks.append({
        "name": "JWT 密钥",
        "ok": not weak,
        "detail": f"长度 {len(secret)}；建议 ≥32 位随机字符串" + ("（当前为默认/弱密钥，请立即更换）" if weak else ""),
    })

    # 存储目录可写
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

    # 外部通知渠道
    try:
        from utils.notify_channels import channel_status
        st = channel_status()
        email_ready = st["email"]["enabled"] and st["email"]["configured"]
        hook_ready = st["webhook"]["enabled"] and st["webhook"]["configured"]
        checks.append({
            "name": "外部通知",
            "ok": True,  # 未配置是正常状态，不算失败
            "detail": ("邮件已启用；" if email_ready else "") + ("Webhook 已启用" if hook_ready else "")
                      + ("（均未配置，仅站内通知）" if not (email_ready or hook_ready) else ""),
        })
    except Exception as e:
        checks.append({"name": "外部通知", "ok": False, "detail": str(e)})

    # 系统配置可读
    try:
        from utils.system_config import get_config
        db = SessionLocal()
        limit = get_config(db, "pool_claim_limit")
        db.close()
        checks.append({"name": "系统配置", "ok": True, "detail": f"可读取（公海限额 {limit}）"})
    except Exception as e:
        checks.append({"name": "系统配置", "ok": False, "detail": str(e)})

    # 调度任务提示（SLA 定时任务需外部 cron 触发）
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


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    """把 Pydantic 校验错误转成前端可直接展示的中文提示。

    默认的 422 响应体是嵌套数组（loc/msg/type），前端 ElMessage 展示会很难看，
    这里提取首条错误并压平成字符串 detail，同时保留完整错误供调试。
    """
    errors = exc.errors()
    messages = []
    safe_errors = []
    for err in errors:
        msg = err.get("msg", "")
        # Pydantic v2 自定义校验的错误信息前缀为 "Value error, "
        msg = msg.replace("Value error, ", "")
        loc = [str(x) for x in err.get("loc", []) if x not in ("body", "query", "path")]
        field = ".".join(loc)
        if field and msg:
            messages.append(f"{field}: {msg}")
        elif msg:
            messages.append(msg)
        # ctx 中可能含 ValueError 等不可 JSON 序列化对象，只保留基础字段
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
