from functools import wraps
from fastapi import Request
from sqlalchemy.orm import Session
from models import OperationLog
from datetime import datetime, timezone
import json
from typing import Optional, Callable, Any


def audit_log(action: str, resource_type: str, get_resource_id: Optional[Callable] = None):
    """
    审计日志装饰器
    
    Args:
        action: 操作类型，如 "CREATE", "UPDATE", "DELETE"
        resource_type: 资源类型，如 "customer", "application"
        get_resource_id: 可选函数，从响应中获取资源 ID
    """
    def decorator(func: Callable):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            from main import logger
            
            request: Optional[Request] = kwargs.get("request")
            db: Optional[Session] = kwargs.get("db")
            current_user = kwargs.get("current_user")
            
            old_value = kwargs.pop("old_value", None)
            
            try:
                result = await func(*args, **kwargs)
                
                if db and current_user:
                    resource_id = None
                    if get_resource_id:
                        resource_id = get_resource_id(result)
                    elif hasattr(result, "id"):
                        resource_id = result.id
                    
                    new_value = None
                    if hasattr(result, "__dict__"):
                        new_value = {
                            k: str(v) if isinstance(v, datetime) else v
                            for k, v in result.__dict__.items()
                            if not k.startswith("_")
                        }
                    
                    try:
                        client_ip = request.client.host if request else None
                        user_agent = request.headers.get("user-agent", "")[:255] if request else None
                        
                        log_entry = OperationLog(
                            user_id=current_user.id,
                            username=current_user.username,
                            action=action,
                            resource_type=resource_type,
                            resource_id=resource_id,
                            old_value=old_value,
                            new_value=new_value,
                            ip_address=client_ip,
                            user_agent=user_agent,
                        )
                        db.add(log_entry)
                        db.commit()
                    except Exception as e:
                        logger.error(f"审计日志记录失败：{e}")
                        db.rollback()
                
                return result
            except Exception as e:
                raise
        return wrapper
    return decorator


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
    """手动记录审计日志"""
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
        db.commit()
    except Exception as e:
        logger.error(f"审计日志记录失败：{e}")
        db.rollback()
