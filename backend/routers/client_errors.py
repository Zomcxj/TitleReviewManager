"""
前端错误上报接口

用途：前端捕获的异常（Vue 渲染错误、未处理的 Promise 拒绝、接口 5xx）
上报到这里，管理员可在界面查看真实错误与频次，而不是依赖用户口头描述。

设计要点：
- **匿名可上报**：登录页出错时用户还没登录，因此不强制鉴权
- **限流**：按 IP 限制（复用 login_attempts 表），防止被刷爆表
- **截断**：message/stack 截断保存，避免超大 payload 撑爆数据库
- **不记录敏感信息**：前端上报前会过滤，后端再做一次长度限制
"""
import logging
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from database import get_db
from models import ClientError, User
from auth import get_current_user, decode_access_token
from utils.request_context import get_client_ip

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/client-errors", tags=["前端错误"])

MAX_MESSAGE_LEN = 2000
MAX_STACK_LEN = 5000
RATE_WINDOW_SECONDS = 300
MAX_REPORTS_PER_WINDOW = 30


class ClientErrorReport(BaseModel):
    message: str = Field(..., max_length=MAX_MESSAGE_LEN)
    stack: Optional[str] = Field(None, max_length=MAX_STACK_LEN)
    url: Optional[str] = Field(None, max_length=500)


def _try_identify_user(request: Request, db: Session):
    """尝试识别上报者（未登录返回 None, None）。

    不强制鉴权：登录页出错的用户还没有 token，强制鉴权会丢掉最关键的一类错误。
    """
    token = request.cookies.get("access_token")
    if not token:
        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            token = auth_header[7:]
    if not token:
        return None, None
    payload = decode_access_token(token)
    if not payload:
        return None, None
    uid = payload.get("user_id") or payload.get("id")
    if not uid:
        return None, None
    user = db.query(User).filter(User.id == uid).first()
    if not user:
        return None, None
    return user.id, user.username


@router.post("/report")
async def report_client_error(
    data: ClientErrorReport,
    request: Request,
    db: Session = Depends(get_db),
):
    """接收前端错误上报（匿名可用，按 IP 限流）"""
    from utils.login_guard import check_ip_rate_limit, record_attempt

    client_ip = get_client_ip(request)
    check_ip_rate_limit(db, f"clienterr:{client_ip}", MAX_REPORTS_PER_WINDOW, RATE_WINDOW_SECONDS)

    user_id, username = _try_identify_user(request, db)

    db.add(ClientError(
        user_id=user_id,
        username=username,
        message=(data.message or "")[:MAX_MESSAGE_LEN],
        stack=(data.stack or "")[:MAX_STACK_LEN] or None,
        url=(data.url or "")[:500] or None,
        user_agent=(request.headers.get("user-agent") or "")[:255] or None,
        ip_address=client_ip,
    ))
    record_attempt(db, f"clienterr:{client_ip}")
    db.commit()

    logger.warning(f"前端错误上报: {data.message[:200]} (user={username or 'anonymous'}, url={data.url})")
    return {"message": "已记录", "received": True}


@router.get("/")
async def list_client_errors(
    page: int = 1,
    page_size: int = 20,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """查看前端错误列表（仅管理员）"""
    if current_user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="只有管理员可以查看前端错误")

    page = max(1, page)
    page_size = min(max(1, page_size), 100)

    query = db.query(ClientError)
    total = query.count()
    items = (
        query.order_by(ClientError.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    return {
        "items": [
            {
                "id": e.id,
                "username": e.username,
                "message": e.message,
                "stack": e.stack,
                "url": e.url,
                "user_agent": e.user_agent,
                "ip_address": e.ip_address,
                "created_at": e.created_at.isoformat() if e.created_at else None,
            }
            for e in items
        ],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


@router.delete("/{error_id}")
async def delete_client_error(
    error_id: int,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """删除单条错误记录（仅管理员）"""
    if current_user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="只有管理员可以操作")
    row = db.query(ClientError).filter(ClientError.id == error_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="记录不存在")
    db.delete(row)
    db.commit()
    return {"message": "已删除"}


@router.delete("/")
async def clear_client_errors(
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """清空所有前端错误记录（仅管理员）"""
    if current_user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="只有管理员可以操作")
    count = db.query(ClientError).delete(synchronize_session=False)
    db.commit()
    return {"message": f"已清空 {count} 条记录", "deleted": count}
