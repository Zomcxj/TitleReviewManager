"""
登录限流与账号锁定（数据库存储）

为什么用数据库而不是进程内存：
    uvicorn 以 --workers N 启动时，每个 worker 是独立进程，内存字典各算各的，
    实际阈值会被放大 N 倍（N 个 worker 各允许 N 次）。生产环境必须共享状态，
    因此改为数据库存储；同时天然支持重启后保留锁定状态。

用法：login 端点调用 check_login_allowed → 校验失败时 record_login_failure →
成功时 reset_login_state。
"""
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


def _now() -> datetime:
    """统一使用 naive UTC，与模型默认值保持一致"""
    return datetime.utcnow()


def _as_naive(dt: Optional[datetime]) -> Optional[datetime]:
    """数据库可能返回 aware 时间（PostgreSQL），统一转 naive 便于比较"""
    if dt is None:
        return None
    return dt.replace(tzinfo=None) if dt.tzinfo is not None else dt


def check_ip_rate_limit(db: Session, ip: str, max_attempts: int, window_seconds: int) -> None:
    """按 IP 限流：窗口内尝试次数超限则拒绝"""
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
    """记录一次 IP 维度的登录尝试"""
    from models import LoginAttempt
    db.add(LoginAttempt(scope="ip", key=ip, attempted_at=_now()))


def check_account_lock(db: Session, username: str) -> None:
    """账号锁定检查：仍在锁定期内则拒绝"""
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
    # 锁定已过期：清除锁定但保留失败计数（计数在下一次失败时继续累加）
    lock.locked_until = None
    db.flush()


def record_failed_login(db: Session, username: str, threshold: int, lock_minutes: int) -> None:
    """记录一次登录失败，达到阈值则锁定账号"""
    from models import AccountLock

    lock = db.query(AccountLock).filter(AccountLock.username == username).first()
    if not lock:
        lock = AccountLock(username=username, failed_count=0)
        db.add(lock)
        db.flush()

    lock.failed_count = (lock.failed_count or 0) + 1
    if lock.failed_count >= threshold:
        lock.locked_until = _now() + timedelta(minutes=lock_minutes)
        lock.failed_count = 0  # 锁定后计数归零，解锁后重新累计
    db.flush()


def reset_login_state(db: Session, username: str) -> None:
    """登录成功：清除该账号的失败计数与锁定"""
    from models import AccountLock
    db.query(AccountLock).filter(AccountLock.username == username).delete(synchronize_session=False)
    db.flush()


def cleanup_old_attempts(db: Session, older_than_hours: int = 24) -> int:
    """清理过期的登录尝试记录，避免表无限增长"""
    from models import LoginAttempt
    cutoff = _now() - timedelta(hours=older_than_hours)
    deleted = db.query(LoginAttempt).filter(LoginAttempt.attempted_at < cutoff).delete(synchronize_session=False)
    db.commit()
    return deleted


def lock_status(db: Session, username: str) -> dict:
    """查询账号锁定状态（供前端提示）"""
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
