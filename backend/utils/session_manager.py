"""
登录会话管理（支持查看活跃设备与单设备下线）

为什么需要会话表：
    JWT 是无状态的，签发后无法单独作废。之前只能靠 user.token_version 做
    「全量下线」（改密时所有设备一起掉线），无法回答：
    - 我当前有哪些设备登录着？
    - 手机丢了，怎么只把手机踢掉而不影响电脑？

    因此在登录时落一条 UserSession，token 里带 session_id，
    认证时校验该会话未被撤销，即可实现按设备管理。
"""
import logging
import re
from datetime import timedelta

from utils.timeutil import utcnow

logger = logging.getLogger(__name__)


def parse_device_label(user_agent: str | None) -> str:
    """从 User-Agent 粗略解析设备描述（不引入 UA 解析库，够用即可）。

    形如 "Chrome / Windows"、"Safari / iPhone"、"未知设备"。
    """
    if not user_agent:
        return "未知设备"
    ua = user_agent

    # 浏览器识别（顺序重要：Edge/Chrome 的 UA 都含 Safari）
    browser = "未知浏览器"
    for pattern, name in (
        (r"Edg/", "Edge"),
        (r"OPR/|Opera", "Opera"),
        (r"MicroMessenger", "微信"),
        (r"Firefox/", "Firefox"),
        (r"Chrome/", "Chrome"),
        (r"Safari/", "Safari"),
        (r"curl/", "curl"),
        (r"python-requests|httpx", "脚本客户端"),
    ):
        if re.search(pattern, ua, re.I):
            browser = name
            break

    # 操作系统 / 设备识别
    os_name = "未知系统"
    for pattern, name in (
        (r"iPhone", "iPhone"),
        (r"iPad", "iPad"),
        (r"Android", "Android"),
        (r"Windows", "Windows"),
        (r"Macintosh|Mac OS X", "macOS"),
        (r"Linux", "Linux"),
    ):
        if re.search(pattern, ua, re.I):
            os_name = name
            break

    if browser == "未知浏览器" and os_name == "未知系统":
        return "未知设备"
    return f"{browser} / {os_name}"


def create_session(
    db,
    user_id: int,
    ip_address: str | None,
    user_agent: str | None,
    expires_minutes: int,
) -> str:
    """创建登录会话并返回 session_id"""
    import secrets

    from models import UserSession

    session_id = secrets.token_urlsafe(32)
    now = utcnow()
    db.add(UserSession(
        session_id=session_id,
        user_id=user_id,
        ip_address=ip_address,
        user_agent=(user_agent or "")[:255] or None,
        device_label=parse_device_label(user_agent),
        created_at=now,
        last_seen_at=now,
        expires_at=now + timedelta(minutes=expires_minutes),
    ))
    db.flush()
    return session_id


def is_session_valid(db, session_id: str | None, user_id: int) -> bool:
    """校验会话是否仍有效（存在、未撤销、未过期）。

    兼容历史 token（无 session_id）：返回 True，由 token_version 机制兜底，
    避免升级后把所有在线用户踢掉。
    """
    if not session_id:
        return True
    from models import UserSession

    session = db.query(UserSession).filter(
        UserSession.session_id == session_id,
        UserSession.user_id == user_id,
    ).first()
    if not session:
        return False
    if session.revoked_at is not None:
        return False
    # 已过期（expires_at 为空表示长期有效）
    return not (session.expires_at and session.expires_at < utcnow())


def touch_session(db, session_id: str | None) -> None:
    """更新会话最近活跃时间（用于界面显示"最后活动"）。

    为降低写放大，仅在距上次更新超过 5 分钟时才写库。
    """
    if not session_id:
        return
    from models import UserSession

    session = db.query(UserSession).filter(UserSession.session_id == session_id).first()
    if not session:
        return
    now = utcnow()
    last = session.last_seen_at or session.created_at
    if last and (now - last).total_seconds() < 300:
        return
    session.last_seen_at = now


def list_sessions(db, user_id: int, current_session_id: str | None = None) -> list[dict]:
    """列出用户的活跃会话（未撤销、未过期），按最近活跃倒序"""
    from models import UserSession

    now = utcnow()
    sessions = (
        db.query(UserSession)
        .filter(
            UserSession.user_id == user_id,
            UserSession.revoked_at.is_(None),
            UserSession.expires_at > now,
        )
        .order_by(UserSession.last_seen_at.desc())
        .all()
    )
    return [
        {
            "session_id": s.session_id,
            "ip_address": s.ip_address,
            "device_label": s.device_label,
            "created_at": s.created_at.isoformat() if s.created_at else None,
            "last_seen_at": s.last_seen_at.isoformat() if s.last_seen_at else None,
            "expires_at": s.expires_at.isoformat() if s.expires_at else None,
            "is_current": s.session_id == current_session_id,
        }
        for s in sessions
    ]


def revoke_session(db, user_id: int, session_id: str) -> bool:
    """撤销指定会话（仅能撤销自己的）"""
    from models import UserSession

    session = db.query(UserSession).filter(
        UserSession.session_id == session_id,
        UserSession.user_id == user_id,
    ).first()
    if not session or session.revoked_at is not None:
        return False
    session.revoked_at = utcnow()
    db.flush()
    return True


def revoke_other_sessions(db, user_id: int, keep_session_id: str | None) -> int:
    """撤销该用户除指定会话外的所有会话（改密时用：保留当前设备）"""
    from models import UserSession

    query = db.query(UserSession).filter(
        UserSession.user_id == user_id,
        UserSession.revoked_at.is_(None),
    )
    if keep_session_id:
        query = query.filter(UserSession.session_id != keep_session_id)
    count = query.update({"revoked_at": utcnow()}, synchronize_session=False)
    db.flush()
    return count


def cleanup_expired_sessions(db, older_than_days: int = 30) -> int:
    """清理过期已久的会话记录，避免表无限增长"""
    from models import UserSession

    cutoff = utcnow() - timedelta(days=older_than_days)
    deleted = db.query(UserSession).filter(UserSession.expires_at < cutoff).delete(
        synchronize_session=False
    )
    db.commit()
    return deleted
