import logging
import re

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from auth import (
    ACCESS_TOKEN_EXPIRE_MINUTES,
    create_access_token,
    get_current_user,
    verify_password,
)
from database import get_db
from models import OperationLog, User
from schemas import LoginRequest, UserResponse
from utils.login_guard import (
    check_account_lock,
    check_ip_rate_limit,
    lock_status,
    record_attempt,
    record_failed_login,
    reset_login_state,
)
from utils.system_config import get_config
from utils.timeutil import utcnow

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/auth", tags=["认证"])

USERNAME_PATTERN = re.compile(r'^[a-zA-Z0-9_]{2,50}$')

# IP rate limiting parameters (the in-memory version is deprecated; these serve only as thresholds for the database-backed rate limiter)
MAX_ATTEMPTS_PER_WINDOW = 100
RATE_WINDOW_SECONDS = 300


def _user_agent(request: Request) -> str:
    return (request.headers.get("user-agent") or "")[:255]


def _write_login_log(db: Session, *, user_id, username, action: str, request: Request,
                     client_ip: str, detail: str = None, resource_id=None):
    """Write a login audit log. A logging failure must never break the login flow, hence the surrounding try/except."""
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
    # Get client IP (resolved from X-Forwarded-For behind reverse proxies, see utils/request_context)
    from utils.request_context import cookie_extra_kwargs, get_client_ip
    client_ip = get_client_ip(request)

    # 1. Rate limiting per IP (database-backed so counters are shared across workers)
    check_ip_rate_limit(db, client_ip, MAX_ATTEMPTS_PER_WINDOW, RATE_WINDOW_SECONDS)

    # Lockout threshold/duration driven by system config (default: 10 attempts locks for 15 minutes)
    lockout_threshold = get_config(db, "login_lockout_threshold")
    lockout_minutes = get_config(db, "login_lockout_minutes")

    # 2. Account lockout check (audit-logged and rejected when locked)
    try:
        check_account_lock(db, req.username)
    except HTTPException:
        # Attempts during lockout still count toward IP rate limiting, preventing endless probing after lockout
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
        # Log only the attempted username; do not reveal whether the user exists
        _write_login_log(
            db, user_id=None, username=req.username,
            action="登录失败", request=request, client_ip=client_ip,
            detail=f"IP: {client_ip}",
        )
        db.commit()
        # Brute-force detection: notify admins when one IP fails many times in a short window
        _alert_brute_force(db, client_ip, req.username)
        raise HTTPException(status_code=401, detail="用户名或密码错误")

    # 5. Reset failed login counter on success
    reset_login_state(db, req.username)
    # Create a session record so the device can be managed/revoked individually
    from utils.session_manager import create_session
    session_id = create_session(
        db=db, user_id=user.id,
        ip_address=client_ip,
        user_agent=request.headers.get("user-agent"),
        expires_minutes=ACCESS_TOKEN_EXPIRE_MINUTES,
    )
    token = create_access_token({
        "user_id": user.id, "id": user.id,
        "username": user.username, "role": user.role,
        "tv": user.token_version or 0,
        "sid": session_id,
    })
    _write_login_log(
        db, user_id=user.id, username=user.username,
        action="登录成功", request=request, client_ip=client_ip,
        resource_id=user.id,
    )
    user_dict = UserResponse.model_validate(user).model_dump(mode="json")
    response_data = {"message": "登录成功", "user": user_dict}
    resp = JSONResponse(content=response_data)
    # Keep the cookie lifetime aligned with the JWT validity (480min) to avoid a stale cookie with an expired token
    resp.set_cookie(
        key="access_token", value=token,
        max_age=ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        **cookie_extra_kwargs(),
    )
    return resp


@router.post("/logout")
async def logout(request: Request, db: Session = Depends(get_db)):
    """Log out: revoke the current session so the token becomes invalid immediately (not just clearing the cookie)"""
    try:
        user_info = await get_current_user(request)
        sid = user_info.get("sid")
        uid = user_info.get("user_id") or user_info.get("id")
        if sid and uid:
            from utils.session_manager import revoke_session
            revoke_session(db, uid, sid)
            db.commit()
    except Exception:
        # When not logged in or the token is already invalid, still return normally and clear the cookie
        pass
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


def _alert_brute_force(db: Session, client_ip: str, username: str) -> None:
    """Brute-force detection: notify all admins when one IP exceeds the failure threshold within the window.

    Notifies only on the single attempt that crosses the threshold (with a 30-minute
    dedup window) to avoid bombarding admins on every failure. Any exception is
    swallowed; this must never affect the login flow.
    """
    try:
        from datetime import timedelta

        from models import LoginAttempt, Notification
        from routers.notifications import create_notification

        window_minutes = 10
        threshold = 20
        since = utcnow() - timedelta(minutes=window_minutes)
        # Count at the IP dimension (progress checks etc. reuse the same table, distinguished by key prefix)
        fails = db.query(LoginAttempt).filter(
            LoginAttempt.scope == "ip",
            LoginAttempt.key == client_ip,
            LoginAttempt.attempted_at >= since,
        ).count()
        if fails < threshold:
            return

        # Dedup: skip if the same IP was already alerted within 30 minutes
        dedup_since = utcnow() - timedelta(minutes=30)
        recent = db.query(Notification).filter(
            Notification.type == "security_alert",
            Notification.created_at >= dedup_since,
            Notification.content.like(f"%{client_ip}%"),
        ).first()
        if recent:
            return

        for admin in db.query(User).filter(User.role == "admin", User.is_deleted == False).all():
            create_notification(
                db=db,
                user_id=admin.id,
                title="安全告警：疑似暴力破解",
                content=(
                    f"IP {client_ip} 在 {window_minutes} 分钟内登录失败 {fails} 次"
                    f"（最近尝试账号：{username}）。请检查是否需要封禁该来源。"
                ),
                type="security_alert",
                related_type="auth",
            )
        db.commit()
        logger.warning(f"暴力破解告警已发送: IP={client_ip}, 失败 {fails} 次")
    except Exception as e:
        logger.error(f"暴力破解告警发送失败: {e}")


@router.get("/lock-status")
async def get_lock_status(request: Request, db: Session = Depends(get_db)):
    """Get the current account lock status (public, unauthenticated; used by the frontend to show remaining wait time)"""
    username = request.query_params.get("username", "")
    if not username:
        return {"locked": False}
    return lock_status(db, username)


@router.get("/sessions")
async def list_my_sessions(request: Request, db: Session = Depends(get_db)):
    """List active login devices for the current account"""
    user_info = await get_current_user(request)
    from utils.session_manager import list_sessions
    uid = user_info.get("user_id") or user_info.get("id")
    items = list_sessions(db, uid, current_session_id=user_info.get("sid"))
    return {"items": items, "total": len(items)}


@router.delete("/sessions/{session_id}")
async def revoke_my_session(session_id: str, request: Request, db: Session = Depends(get_db)):
    """Revoke a specific device (only one's own sessions)"""
    user_info = await get_current_user(request)
    from utils.session_manager import revoke_session
    uid = user_info.get("user_id") or user_info.get("id")
    if not revoke_session(db, uid, session_id):
        raise HTTPException(status_code=404, detail="会话不存在或已下线")
    db.commit()
    return {"message": "该设备已下线"}


@router.post("/sessions/revoke-others")
async def revoke_other_sessions(request: Request, db: Session = Depends(get_db)):
    """Revoke all devices except the current one (use when account theft is suspected)"""
    user_info = await get_current_user(request)
    from utils.session_manager import revoke_other_sessions as revoke_others
    uid = user_info.get("user_id") or user_info.get("id")
    count = revoke_others(db, uid, keep_session_id=user_info.get("sid"))
    db.commit()
    return {"message": f"已下线 {count} 台其他设备", "count": count}
