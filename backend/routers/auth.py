from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session
from database import get_db
from models import User, OperationLog
from schemas import LoginRequest, UserResponse
from auth import (
    verify_password, create_access_token, get_current_user,
    check_rate_limit, record_attempt,
    reset_failed_login, ACCESS_TOKEN_EXPIRE_MINUTES,
)
from utils.system_config import get_config
from datetime import datetime
import time
import re

router = APIRouter(prefix="/api/auth", tags=["认证"])

USERNAME_PATTERN = re.compile(r'^[a-zA-Z0-9_]{2,50}$')


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


def _check_account_lock_with_config(username: str, threshold: int) -> None:
    """锁定判定（阈值/时长由系统配置驱动）。

    不复用 backend/auth.py 的 check_account_lock：该函数在"未锁定"分支会直接删除
    计数记录（locked_until 初始为 0，恒满足 <= now），导致失败次数无法累积、锁定永不触发。
    这里本地实现，未达阈值时保留计数，仅当锁定已过期才重置。
    """
    from auth import _account_locks
    lock = _account_locks.get(username)
    if not lock:
        return
    now = time.time()
    if lock["locked_until"] > now:
        remaining = int(lock["locked_until"] - now)
        raise HTTPException(
            status_code=429,
            detail=f"账号已被锁定，请在 {remaining // 60} 分 {remaining % 60} 秒后重试",
        )
    # 曾经锁定且锁定期已过：清零重新计数；未达阈值则保留计数继续累积
    if lock.get("locked_until") and lock.get("count", 0) >= threshold:
        del _account_locks[username]


def _record_failed_login_with_config(username: str, threshold: int, lock_minutes: int) -> None:
    """按系统配置记录一次登录失败并判定是否锁定。

    阈值/锁定时长由系统配置 login_lockout_threshold / login_lockout_minutes 驱动，
    默认 10 次锁 15 分钟（原先硬编码为 50 次、15 分钟）。
    复用 backend/auth.py 的 _account_locks 存储，使锁定状态在进程内共享。
    """
    from auth import _account_locks
    if username not in _account_locks:
        _account_locks[username] = {"count": 0, "locked_until": 0}
    _account_locks[username]["count"] += 1
    if _account_locks[username]["count"] >= threshold:
        _account_locks[username]["locked_until"] = time.time() + lock_minutes * 60


@router.post("/login")
async def login(req: LoginRequest, request: Request, db: Session = Depends(get_db)):
    # Get client IP
    client_ip = request.client.host if request.client else "unknown"

    # 1. Rate limiting per IP
    check_rate_limit(client_ip)

    # 锁定阈值/时长改由系统配置驱动（默认 10 次锁 15 分钟，原硬编码 50 次）
    lockout_threshold = get_config(db, "login_lockout_threshold")
    lockout_minutes = get_config(db, "login_lockout_minutes")

    # 2. Account lockout check（被锁定时记录审计并拒绝）
    try:
        _check_account_lock_with_config(req.username, lockout_threshold)
    except HTTPException:
        _write_login_log(
            db, user_id=None, username=req.username,
            action="登录被拒（账号锁定）", request=request, client_ip=client_ip,
            detail=f"IP: {client_ip}",
        )
        raise

    # 3. Input validation
    if not USERNAME_PATTERN.match(req.username):
        record_attempt(client_ip)
        raise HTTPException(status_code=400, detail="用户名格式不正确，只能包含字母、数字和下划线")

    if not req.password:
        record_attempt(client_ip)
        raise HTTPException(status_code=400, detail="密码不能为空")

    # 4. Verify credentials
    user = db.query(User).filter(User.username == req.username).first()
    if not user or not user.password_hash or not verify_password(req.password, user.password_hash):
        record_attempt(client_ip)
        _record_failed_login_with_config(req.username, lockout_threshold, lockout_minutes)
        # 仅记录尝试的用户名，不暴露用户是否存在
        _write_login_log(
            db, user_id=None, username=req.username,
            action="登录失败", request=request, client_ip=client_ip,
            detail=f"IP: {client_ip}",
        )
        raise HTTPException(status_code=401, detail="用户名或密码错误")

    # 5. Reset failed login counter on success
    reset_failed_login(req.username)
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
async def get_lock_status(request: Request):
    """获取当前账号锁定状态（公开接口，不认证）"""
    from auth import _account_locks, _login_attempts
    import time
    username = request.query_params.get("username", "")
    if not username:
        return {"locked": False}
    if username in _account_locks:
        lock = _account_locks[username]
        if lock["locked_until"] > time.time():
            return {
                "locked": True,
                "remaining_seconds": int(lock["locked_until"] - time.time()),
                "failed_count": lock["count"],
            }
    return {"locked": False, "failed_count": _account_locks.get(username, {}).get("count", 0)}
