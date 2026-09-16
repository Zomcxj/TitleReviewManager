from fastapi import Request
from sqlalchemy.orm import Session
from models import OperationLog
from typing import Optional


def manual_audit_log(
    db: Session,
    user_id: int,
    username: str,
    action: str,
    resource_type: str,
    resource_id: Optional[int],
    old_value: Optional[dict] = None,
    new_value: Optional[dict] = None,
    request: Optional[Request] = None,
):
    """手动记录审计日志。只加入会话，随调用方的事务一起提交，避免打断/回滚主业务。"""
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
