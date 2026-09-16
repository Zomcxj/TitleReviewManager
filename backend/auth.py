import os
from passlib.context import CryptContext
from jose import jwt, JWTError
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
    except JWTError:
        return None


async def get_current_user(request: Request) -> dict:
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
    return payload


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
