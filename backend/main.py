from fastapi import FastAPI, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse
from database import engine, Base
from routers import auth, customers, applications, materials, reviews, feedback, registration, audit, exports, notifications, follow_ups, public_pool, batch, dashboard
import os, logging
from datetime import datetime, timezone

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", handlers=[logging.StreamHandler()])
logger = logging.getLogger(__name__)

Base.metadata.create_all(bind=engine)

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

uploads_dir = os.path.join(os.path.dirname(__file__), "uploads")
if os.path.exists(uploads_dir):
    app.mount("/uploads", StaticFiles(directory=uploads_dir), name="uploads")

@app.get("/api/health")
async def health():
    try:
        from database import SessionLocal, text
        db = SessionLocal()
        db.execute(text("SELECT 1"))
        db.close()
        return {"status": "ok", "database": "connected", "timestamp": datetime.now(timezone.utc).isoformat()}
    except Exception as e:
        return {"status": "error", "database": str(e), "timestamp": datetime.now(timezone.utc).isoformat()}

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.error(f"Unhandled exception: {exc}", exc_info=True)
    return JSONResponse(status_code=500, content={"detail": "Internal server error", "type": type(exc).__name__})

@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    if exc.status_code >= 500:
        logger.error(f"HTTP error {exc.status_code}: {exc.detail}")
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})
