import os
from passlib.context import CryptContext
import jwt
from datetime import datetime, timedelta, timezone
from fastapi import Request, HTTPException
from typing import Optional, Dict, List
import time

SECRET_KEY = os.getenv("JWT_SECRET_KEY")
if not SECRET_KEY:
    raise RuntimeError("环境变量 JWT_SECRET_KEY 未设置。请在 .env 文件或系统环境中配置它。")

ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 480

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# Rate limiting: IP -> list of timestamps
_login_attempts: Dict[str, List[float]] = {}
# Account lockout: username -> {count, locked_until}
_account_locks: Dict[str, Dict] = {}

MAX_ATTEMPTS_PER_WINDOW = 100
RATE_WINDOW_SECONDS = 300  # 5 minutes
LOCKOUT_THRESHOLD = 50
LOCKOUT_DURATION_SECONDS = 900  # 15 minutes


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)


def check_rate_limit(ip: str) -> None:
    now = time.time()
    if ip not in _login_attempts:
        _login_attempts[ip] = []
    # Remove attempts outside the window
    _login_attempts[ip] = [t for t in _login_attempts[ip] if now - t < RATE_WINDOW_SECONDS]
    if len(_login_attempts[ip]) >= MAX_ATTEMPTS_PER_WINDOW:
        remaining = RATE_WINDOW_SECONDS - (now - _login_attempts[ip][0])
        raise HTTPException(
            status_code=429,
            detail=f"登录尝试过于频繁，请在 {int(remaining)} 秒后重试",
        )


def record_attempt(ip: str) -> None:
    now = time.time()
    if ip not in _login_attempts:
        _login_attempts[ip] = []
    _login_attempts[ip].append(now)


def check_account_lock(username: str) -> None:
    if username in _account_locks:
        lock = _account_locks[username]
        if lock["locked_until"] > time.time():
            remaining = int(lock["locked_until"] - time.time())
            raise HTTPException(
                status_code=429,
                detail=f"账号已被锁定，请在 {remaining // 60} 分 {remaining % 60} 秒后重试",
            )
        else:
            del _account_locks[username]


def record_failed_login(username: str) -> None:
    if username not in _account_locks:
        _account_locks[username] = {"count": 0, "locked_until": 0}
    _account_locks[username]["count"] += 1
    if _account_locks[username]["count"] >= LOCKOUT_THRESHOLD:
        _account_locks[username]["locked_until"] = time.time() + LOCKOUT_DURATION_SECONDS


def reset_failed_login(username: str) -> None:
    if username in _account_locks:
        del _account_locks[username]


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + (expires_delta or timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES))
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


def decode_access_token(token: str) -> Optional[dict]:
    try:
        return jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    except jwt.PyJWTError:
        return None


async def get_current_user(request: Request) -> dict:
    """解析并校验当前用户。

    除签名与过期时间外，还回查数据库校验：
    - 用户仍存在且未被软删除（此前删除用户后其 token 仍可用满 8 小时）
    - token 中的版本号与用户当前 token_version 一致
      （改密 / 管理员重置密码 / 删除用户后会自增，使旧 token 立即失效）

    代价是每个请求一次主键查询（有索引），对内部管理系统可接受。
    """
    token = request.cookies.get("access_token")
    if not token:
        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            token = auth_header[7:]
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")
    payload = decode_access_token(token)
    if payload is None:
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    # 回查数据库确认账号有效性与 token 版本。
    # 注意：本函数在路由内被直接 await 调用（非 Depends），因此这里取的是
    # database.SessionLocal；测试通过 conftest 把该工厂指向内存库。
    uid = payload.get("user_id") or payload.get("id")
    if not uid:
        raise HTTPException(status_code=401, detail="Invalid token payload")

    from database import SessionLocal
    from models import User
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.id == uid, User.is_deleted == False).first()
        if not user:
            raise HTTPException(status_code=401, detail="账号不存在或已被删除")
        token_version = payload.get("tv")
        # 兼容旧 token（无 tv 字段）：视为版本 0
        if (token_version or 0) != (user.token_version or 0):
            raise HTTPException(status_code=401, detail="登录状态已失效，请重新登录")
        # 校验会话未被撤销/过期（支持按设备下线；旧 token 无 sid 时跳过）
        from utils.session_manager import is_session_valid, touch_session
        sid = payload.get("sid")
        if not is_session_valid(db, sid, user.id):
            raise HTTPException(status_code=401, detail="该设备已被下线，请重新登录")
        touch_session(db, sid)
        # 以数据库为准回填角色，避免 token 中的旧角色被继续使用
        payload["role"] = user.role
        payload["username"] = user.username
        # 显式带上会话标识，供 /auth/sessions 标记"当前设备"
        payload["sid"] = sid
    finally:
        db.close()

    return payload


def bump_token_version(db, user_id: int) -> None:
    """自增用户 token 版本，使其所有已签发的 token 立即失效。

    调用时机：用户改密、管理员重置密码、删除用户、强制下线。
    """
    from models import User
    user = db.query(User).filter(User.id == user_id).first()
    if user:
        user.token_version = (user.token_version or 0) + 1


def require_role(*required_roles):
    """依赖项工厂：校验 JWT 并回查数据库，确保用户仍存在且角色为最新值。
    支持可变参数 require_role("admin", "salesman") 或传列表 require_role(["admin", "salesman"])。"""
    from fastapi import Depends
    from sqlalchemy.orm import Session
    from database import get_db

    if len(required_roles) == 1 and isinstance(required_roles[0], (list, tuple, set)):
        required = set(required_roles[0])
    else:
        required = set(required_roles)

    def check_role(user: dict = Depends(get_current_user), db: Session = Depends(get_db)):
        from models import User
        uid = user.get("user_id") or user.get("id")
        u = db.query(User).filter(User.id == uid).first() if uid else None
        if not u:
            raise HTTPException(status_code=401, detail="用户不存在或已删除")
        if u.role not in required:
            raise HTTPException(status_code=403, detail="Insufficient permissions")
        return {"user_id": u.id, "id": u.id, "username": u.username, "role": u.role}
    return check_role
