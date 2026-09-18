from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session
from database import get_db
from models import User, OperationLog
from schemas import LoginRequest, UserResponse
from auth import (
    verify_password, create_access_token, get_current_user,
    ACCESS_TOKEN_EXPIRE_MINUTES,
)
from utils.login_guard import (
    check_ip_rate_limit, record_attempt, check_account_lock,
    record_failed_login, reset_login_state, lock_status,
)
from utils.system_config import get_config
from datetime import datetime
import re

router = APIRouter(prefix="/api/auth", tags=["认证"])

USERNAME_PATTERN = re.compile(r'^[a-zA-Z0-9_]{2,50}$')

# IP 限流参数（内存态版本已废弃，此处仅作为数据库限流的阈值配置）
MAX_ATTEMPTS_PER_WINDOW = 100
RATE_WINDOW_SECONDS = 300


def _user_agent(request: Request) -> str:
    return (request.headers.get("user-agent") or "")[:255]


def _write_login_log(db: Session, *, user_id, username, action: str, request: Request,
                     client_ip: str, detail: str = None, resource_id=None):
    """写入登录审计日志。日志失败绝不能影响登录流程，因此整体 try/except 包裹。"""
    try:
        db.add(OperationLog(
            user_id=user_id,
            username=username,
            action=action,
            resource_type="auth",
            resource_id=resource_id,
            new_value={"detail": detail} if detail else None,
            ip_address=client_ip,
            user_agent=_user_agent(request),
        ))
        db.commit()
    except Exception:
        db.rollback()


@router.post("/login")
async def login(req: LoginRequest, request: Request, db: Session = Depends(get_db)):
    # Get client IP
    client_ip = request.client.host if request.client else "unknown"

    # 1. Rate limiting per IP（数据库存储，多 worker 共享计数）
    check_ip_rate_limit(db, client_ip, MAX_ATTEMPTS_PER_WINDOW, RATE_WINDOW_SECONDS)

    # 锁定阈值/时长由系统配置驱动（默认 10 次锁 15 分钟）
    lockout_threshold = get_config(db, "login_lockout_threshold")
    lockout_minutes = get_config(db, "login_lockout_minutes")

    # 2. Account lockout check（被锁定时记录审计并拒绝）
    try:
        check_account_lock(db, req.username)
    except HTTPException:
        # 锁定期内的尝试也计入 IP 限流，避免被锁后继续无限试探
        record_attempt(db, client_ip)
        _write_login_log(
            db, user_id=None, username=req.username,
            action="登录被拒（账号锁定）", request=request, client_ip=client_ip,
            detail=f"IP: {client_ip}",
        )
        db.commit()
        raise

    # 3. Input validation
    if not USERNAME_PATTERN.match(req.username):
        record_attempt(db, client_ip)
        db.commit()
        raise HTTPException(status_code=400, detail="用户名格式不正确，只能包含字母、数字和下划线")

    if not req.password:
        record_attempt(db, client_ip)
        db.commit()
        raise HTTPException(status_code=400, detail="密码不能为空")

    # 4. Verify credentials
    user = db.query(User).filter(User.username == req.username).first()
    if not user or not user.password_hash or not verify_password(req.password, user.password_hash):
        record_attempt(db, client_ip)
        record_failed_login(db, req.username, lockout_threshold, lockout_minutes)
        # 仅记录尝试的用户名，不暴露用户是否存在
        _write_login_log(
            db, user_id=None, username=req.username,
            action="登录失败", request=request, client_ip=client_ip,
            detail=f"IP: {client_ip}",
        )
        db.commit()
        raise HTTPException(status_code=401, detail="用户名或密码错误")

    # 5. Reset failed login counter on success
    reset_login_state(db, req.username)
    token = create_access_token({"user_id": user.id, "id": user.id, "username": user.username, "role": user.role})
    _write_login_log(
        db, user_id=user.id, username=user.username,
        action="登录成功", request=request, client_ip=client_ip,
        resource_id=user.id,
    )
    user_dict = UserResponse.model_validate(user).model_dump(mode="json")
    response_data = {"message": "登录成功", "user": user_dict}
    resp = JSONResponse(content=response_data)
    # Cookie 生命周期与 JWT 有效期(480min)保持一致，避免 cookie 残留但 token 已过期
    resp.set_cookie(key="access_token", value=token, httponly=True, samesite="lax", max_age=ACCESS_TOKEN_EXPIRE_MINUTES * 60)
    return resp


@router.post("/logout")
async def logout():
    resp = JSONResponse(content={"message": "已退出"})
    resp.delete_cookie(key="access_token")
    return resp


@router.get("/me", response_model=UserResponse)
async def get_me(request: Request, db: Session = Depends(get_db)):
    user_info = await get_current_user(request)
    user = db.query(User).filter(User.id == user_info["user_id"]).first()
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")
    return UserResponse.model_validate(user)


@router.get("/lock-status")
async def get_lock_status(request: Request, db: Session = Depends(get_db)):
    """获取当前账号锁定状态（公开接口，不认证，用于前端提示剩余等待时间）"""
    username = request.query_params.get("username", "")
    if not username:
        return {"locked": False}
    return lock_status(db, username)
