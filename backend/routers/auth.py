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
import logging

logger = logging.getLogger(__name__)

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
    # Get client IP（反代场景下从 X-Forwarded-For 解析，见 utils/request_context）
    from utils.request_context import get_client_ip, cookie_extra_kwargs
    client_ip = get_client_ip(request)

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
        # 暴力破解检测：同一 IP 短时间内大量失败时通知管理员
        _alert_brute_force(db, client_ip, req.username)
        raise HTTPException(status_code=401, detail="用户名或密码错误")

    # 5. Reset failed login counter on success
    reset_login_state(db, req.username)
    # 创建会话记录，使该设备可被单独管理/下线
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
    # Cookie 生命周期与 JWT 有效期(480min)保持一致，避免 cookie 残留但 token 已过期
    resp.set_cookie(
        key="access_token", value=token,
        max_age=ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        **cookie_extra_kwargs(),
    )
    return resp


@router.post("/logout")
async def logout(request: Request, db: Session = Depends(get_db)):
    """退出登录：撤销当前会话，使该 token 立即失效（而不仅是清 cookie）"""
    try:
        user_info = await get_current_user(request)
        sid = user_info.get("sid")
        uid = user_info.get("user_id") or user_info.get("id")
        if sid and uid:
            from utils.session_manager import revoke_session
            revoke_session(db, uid, sid)
            db.commit()
    except Exception:
        # 未登录或 token 已失效时，仍应正常返回并清 cookie
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
    """暴力破解检测：同一 IP 在窗口内失败次数超阈值时通知全部管理员。

    仅在跨过阈值的**那一次**发通知（用 30 分钟去重窗口），避免每次失败都轰炸。
    任何异常都吞掉，绝不能影响登录流程。
    """
    try:
        from datetime import timedelta
        from models import LoginAttempt, Notification
        from routers.notifications import create_notification

        window_minutes = 10
        threshold = 20
        since = datetime.utcnow() - timedelta(minutes=window_minutes)
        # 统计该 IP 维度（含进度查询等复用同一表，用 key 前缀区分）
        fails = db.query(LoginAttempt).filter(
            LoginAttempt.scope == "ip",
            LoginAttempt.key == client_ip,
            LoginAttempt.attempted_at >= since,
        ).count()
        if fails < threshold:
            return

        # 去重：30 分钟内已告警过同一 IP 则跳过
        dedup_since = datetime.utcnow() - timedelta(minutes=30)
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
    """获取当前账号锁定状态（公开接口，不认证，用于前端提示剩余等待时间）"""
    username = request.query_params.get("username", "")
    if not username:
        return {"locked": False}
    return lock_status(db, username)


@router.get("/sessions")
async def list_my_sessions(request: Request, db: Session = Depends(get_db)):
    """列出当前账号的活跃登录设备"""
    user_info = await get_current_user(request)
    from utils.session_manager import list_sessions
    uid = user_info.get("user_id") or user_info.get("id")
    items = list_sessions(db, uid, current_session_id=user_info.get("sid"))
    return {"items": items, "total": len(items)}


@router.delete("/sessions/{session_id}")
async def revoke_my_session(session_id: str, request: Request, db: Session = Depends(get_db)):
    """下线指定设备（只能操作自己的会话）"""
    user_info = await get_current_user(request)
    from utils.session_manager import revoke_session
    uid = user_info.get("user_id") or user_info.get("id")
    if not revoke_session(db, uid, session_id):
        raise HTTPException(status_code=404, detail="会话不存在或已下线")
    db.commit()
    return {"message": "该设备已下线"}


@router.post("/sessions/revoke-others")
async def revoke_other_sessions(request: Request, db: Session = Depends(get_db)):
    """下线除当前设备外的所有设备（怀疑账号被盗时使用）"""
    user_info = await get_current_user(request)
    from utils.session_manager import revoke_other_sessions as revoke_others
    uid = user_info.get("user_id") or user_info.get("id")
    count = revoke_others(db, uid, keep_session_id=user_info.get("sid"))
    db.commit()
    return {"message": f"已下线 {count} 台其他设备", "count": count}
