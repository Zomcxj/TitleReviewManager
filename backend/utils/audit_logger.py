
from fastapi import Request
from sqlalchemy.orm import Session

from models import OperationLog


def manual_audit_log(
    db: Session,
    user_id: int,
    username: str,
    action: str,
    resource_type: str,
    resource_id: int | None,
    old_value: dict | None = None,
    new_value: dict | None = None,
    request: Request | None = None,
):
    """Record an audit log entry manually. Only adds to the session and commits with the caller's transaction, so the main business is never interrupted/rolled back."""
    from main import logger

    try:
        client_ip = request.client.host if request else None
        user_agent = request.headers.get("user-agent", "")[:255] if request else None

        log_entry = OperationLog(
            user_id=user_id,
            username=username,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            old_value=old_value,
            new_value=new_value,
            ip_address=client_ip,
            user_agent=user_agent,
        )
        db.add(log_entry)
    except Exception as e:
        logger.error(f"审计日志记录失败：{e}")
