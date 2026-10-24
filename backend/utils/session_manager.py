"""
Login session management (active device listing and per-device logout)

Why a session table is needed:
    JWT is stateless — once issued, a token cannot be revoked individually. Before,
    only user.token_version provided a "log out everywhere" switch (all devices drop
    on password change), which cannot answer:
    - Which devices are logged in right now?
    - My phone is lost — how do I kick just the phone without affecting the computer?

    So a UserSession row is created at login, the token carries a session_id, and
    authentication verifies the session is not revoked — enabling per-device management.
"""
import logging
import re
from datetime import timedelta

from utils.timeutil import utcnow

logger = logging.getLogger(__name__)


def parse_device_label(user_agent: str | None) -> str:
    """Roughly parse a device label from the User-Agent (no UA parsing library; good enough).

    Examples: "Chrome / Windows", "Safari / iPhone", or "未知设备" (unknown device).
    """
    if not user_agent:
        return "未知设备"
    ua = user_agent

    # Browser detection (order matters: both Edge/Chrome UAs contain Safari)
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

    # Operating system / device detection
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
    """Create a login session and return its session_id"""
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
    """Check whether the session is still valid (exists, not revoked, not expired).

    Backward compatibility for legacy tokens (no session_id): returns True, with
    token_version as the safety net, so the upgrade does not kick all online users.
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
    # Expired (a null expires_at means long-lived)
    return not (session.expires_at and session.expires_at < utcnow())


def touch_session(db, session_id: str | None) -> None:
    """Update the session's last-active time (for showing "last activity" in the UI).

    To reduce write amplification, only writes when more than 5 minutes have passed
    since the last update.
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
    """List the user's active sessions (not revoked, not expired), most recent first"""
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
    """Revoke the given session (only one's own sessions)"""
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
    """Revoke all of the user's sessions except the given one (used on password change: keep the current device)"""
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
    """Clean up long-expired session records to keep the table from growing unbounded"""
    from models import UserSession

    cutoff = utcnow() - timedelta(days=older_than_days)
    deleted = db.query(UserSession).filter(UserSession.expires_at < cutoff).delete(
        synchronize_session=False
    )
    db.commit()
    return deleted
