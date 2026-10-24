"""
Login rate limiting and account lockout (database-backed)

Why a database instead of in-process memory:
    When uvicorn starts with --workers N, each worker is a separate process with its
    own in-memory dict, so the effective threshold is multiplied by N (each of the N
    workers allows N attempts). Production must share state, hence database storage;
    this also preserves lockout state across restarts for free.

Usage: the login endpoint calls check_login_allowed -> record_login_failure on
failed validation -> reset_login_state on success.
"""
import logging
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from utils.timeutil import utcnow

logger = logging.getLogger(__name__)


def _now() -> datetime:
    """Always use naive UTC, consistent with model defaults"""
    return utcnow()


def _as_naive(dt: datetime | None) -> datetime | None:
    """The database may return aware datetimes (PostgreSQL); normalize to naive for comparison"""
    if dt is None:
        return None
    return dt.replace(tzinfo=None) if dt.tzinfo is not None else dt


def check_ip_rate_limit(db: Session, ip: str, max_attempts: int, window_seconds: int) -> None:
    """Rate limit by IP: reject when attempts within the window exceed the cap"""
    from fastapi import HTTPException

    from models import LoginAttempt

    since = _now() - timedelta(seconds=window_seconds)
    count = db.query(LoginAttempt).filter(
        LoginAttempt.scope == "ip",
        LoginAttempt.key == ip,
        LoginAttempt.attempted_at >= since,
    ).count()

    if count >= max_attempts:
        oldest = db.query(LoginAttempt).filter(
            LoginAttempt.scope == "ip",
            LoginAttempt.key == ip,
            LoginAttempt.attempted_at >= since,
        ).order_by(LoginAttempt.attempted_at.asc()).first()
        remaining = window_seconds
        if oldest:
            elapsed = (_now() - _as_naive(oldest.attempted_at)).total_seconds()
            remaining = max(1, int(window_seconds - elapsed))
        raise HTTPException(
            status_code=429,
            detail=f"登录尝试过于频繁，请在 {remaining} 秒后重试",
        )


def record_attempt(db: Session, ip: str) -> None:
    """Record one IP-scoped login attempt"""
    from models import LoginAttempt
    db.add(LoginAttempt(scope="ip", key=ip, attempted_at=_now()))


def check_account_lock(db: Session, username: str) -> None:
    """Account lockout check: reject while still locked"""
    from fastapi import HTTPException

    from models import AccountLock

    lock = db.query(AccountLock).filter(AccountLock.username == username).first()
    if not lock or not lock.locked_until:
        return
    locked_until = _as_naive(lock.locked_until)
    if locked_until and locked_until > _now():
        remaining = int((locked_until - _now()).total_seconds())
        raise HTTPException(
            status_code=429,
            detail=f"账号已被锁定，请在 {remaining // 60} 分 {remaining % 60} 秒后重试",
        )
    # Lockout expired: clear the lock but keep the failure count (it keeps accumulating on the next failure)
    lock.locked_until = None
    db.flush()


def record_failed_login(db: Session, username: str, threshold: int, lock_minutes: int) -> None:
    """Record one failed login; lock the account once the threshold is reached"""
    from models import AccountLock

    lock = db.query(AccountLock).filter(AccountLock.username == username).first()
    if not lock:
        lock = AccountLock(username=username, failed_count=0)
        db.add(lock)
        db.flush()

    lock.failed_count = (lock.failed_count or 0) + 1
    if lock.failed_count >= threshold:
        lock.locked_until = _now() + timedelta(minutes=lock_minutes)
        lock.failed_count = 0  # Reset the counter on lockout; it re-accumulates after unlock
    db.flush()


def reset_login_state(db: Session, username: str) -> None:
    """Successful login: clear the account's failure count and lockout"""
    from models import AccountLock
    db.query(AccountLock).filter(AccountLock.username == username).delete(synchronize_session=False)
    db.flush()


def cleanup_old_attempts(db: Session, older_than_hours: int = 24) -> int:
    """Clean up expired login attempt records to keep the table from growing unbounded"""
    from models import LoginAttempt
    cutoff = _now() - timedelta(hours=older_than_hours)
    deleted = db.query(LoginAttempt).filter(LoginAttempt.attempted_at < cutoff).delete(synchronize_session=False)
    db.commit()
    return deleted


def lock_status(db: Session, username: str) -> dict:
    """Query the account lockout status (for frontend display)"""
    from models import AccountLock
    lock = db.query(AccountLock).filter(AccountLock.username == username).first()
    if not lock:
        return {"locked": False, "failed_count": 0}
    locked_until = _as_naive(lock.locked_until)
    if locked_until and locked_until > _now():
        return {
            "locked": True,
            "remaining_seconds": int((locked_until - _now()).total_seconds()),
            "failed_count": lock.failed_count or 0,
        }
    return {"locked": False, "failed_count": lock.failed_count or 0}
