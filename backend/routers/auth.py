from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session
from database import get_db
from models import User
from schemas import LoginRequest, UserResponse
from auth import (
    verify_password, create_access_token, get_current_user,
    check_rate_limit, record_attempt, check_account_lock,
    record_failed_login, reset_failed_login,
)
import re

router = APIRouter(prefix="/api/auth", tags=["认证"])

USERNAME_PATTERN = re.compile(r'^[a-zA-Z0-9_]{2,50}$')
PASSWORD_MIN_LENGTH = 6


@router.post("/login")
async def login(req: LoginRequest, request: Request, db: Session = Depends(get_db)):
    # Get client IP
    client_ip = request.client.host if request.client else "unknown"

    # 1. Rate limiting per IP
    check_rate_limit(client_ip)

    # 2. Account lockout check
    check_account_lock(req.username)

    # 3. Input validation
    if not USERNAME_PATTERN.match(req.username):
        record_attempt(client_ip)
        raise HTTPException(status_code=400, detail="用户名格式不正确，只能包含字母、数字和下划线")

    if not req.password:
        record_attempt(client_ip)
        raise HTTPException(status_code=400, detail="密码不能为空")

    # 4. Verify credentials
    user = db.query(User).filter(User.username == req.username).first()
    if not user or not verify_password(req.password, user.password_hash):
        record_attempt(client_ip)
        record_failed_login(req.username)
        raise HTTPException(status_code=401, detail="用户名或密码错误")

    # 5. Reset failed login counter on success
    reset_failed_login(req.username)
    token = create_access_token({"user_id": user.id, "id": user.id, "username": user.username, "role": user.role})
    user_dict = UserResponse.model_validate(user).model_dump(mode="json")
    response_data = {"message": "登录成功", "user": user_dict}
    resp = JSONResponse(content=response_data)
    resp.set_cookie(key="access_token", value=token, httponly=True, samesite="lax", max_age=86400)
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
