import os
from datetime import datetime, timedelta, timezone

import jwt
from fastapi import HTTPException, Request
from passlib.context import CryptContext

SECRET_KEY = os.getenv("JWT_SECRET_KEY")
if not SECRET_KEY:
    raise RuntimeError("环境变量 JWT_SECRET_KEY 未设置。请在 .env 文件或系统环境中配置它。")

ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 480

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)


def create_access_token(data: dict, expires_delta: timedelta | None = None) -> str:
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + (expires_delta or timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES))
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


def decode_access_token(token: str) -> dict | None:
    try:
        return jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    except jwt.PyJWTError:
        return None


async def get_current_user(request: Request) -> dict:
    """Parse and validate the current user.

    Beyond signature and expiry, it also re-checks the database to verify:
    - the user still exists and is not soft-deleted (previously a deleted user's token
      remained valid for the full 8 hours)
    - the version number in the token matches the user's current token_version
      (incremented on password change / admin password reset / user deletion, so old
      tokens become invalid immediately)

    The cost is one primary-key query (indexed) per request, acceptable for an
    internal management system.
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

    # Re-check the database to confirm account validity and token version.
    # Note: this function is awaited directly inside routes (not via Depends), so it takes
    # database.SessionLocal; tests point that factory at the in-memory DB via conftest.
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
        # Backward compatibility with old tokens (no tv field): treat as version 0
        if (token_version or 0) != (user.token_version or 0):
            raise HTTPException(status_code=401, detail="登录状态已失效，请重新登录")
        # Verify the session is not revoked/expired (supports per-device sign-out; skipped for old tokens without sid)
        from utils.session_manager import is_session_valid, touch_session
        sid = payload.get("sid")
        if not is_session_valid(db, sid, user.id):
            raise HTTPException(status_code=401, detail="该设备已被下线，请重新登录")
        touch_session(db, sid)
        # Backfill the role from the database so a stale role in the token is not kept in use
        payload["role"] = user.role
        payload["username"] = user.username
        # Explicitly carry the session id so /auth/sessions can mark the "current device"
        payload["sid"] = sid
    finally:
        db.close()

    return payload


def require_role(*required_roles):
    """Dependency factory: validates the JWT and re-checks the database, ensuring the user still
    exists with the latest role. Accepts varargs require_role("admin", "salesman") or a list require_role(["admin", "salesman"])."""
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
