"""
Frontend error reporting API

Purpose: exceptions caught by the frontend (Vue render errors, unhandled Promise
rejections, API 5xx responses) are reported here so admins can see real errors and
their frequency instead of relying on verbal user reports.

Design notes:
- **Anonymous reporting allowed**: users may hit errors on the login page before
  authenticating, so auth is not enforced
- **Rate limiting**: per-IP limits (reusing the login_attempts table) to prevent
  flooding the table
- **Truncation**: message/stack are truncated on save so oversized payloads do not
  blow up the database
- **No sensitive data**: the frontend filters before reporting, and the backend
  applies a length limit as a second line of defense
"""
import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from auth import decode_access_token, get_current_user
from database import get_db
from models import ClientError, User
from utils.request_context import get_client_ip

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/client-errors", tags=["前端错误"])

MAX_MESSAGE_LEN = 2000
MAX_STACK_LEN = 5000
RATE_WINDOW_SECONDS = 300
MAX_REPORTS_PER_WINDOW = 30


class ClientErrorReport(BaseModel):
    message: str = Field(..., max_length=MAX_MESSAGE_LEN)
    stack: str | None = Field(None, max_length=MAX_STACK_LEN)
    url: str | None = Field(None, max_length=500)


def _try_identify_user(request: Request, db: Session):
    """Try to identify the reporter (returns None, None when not logged in).

    Auth is not enforced: users who hit errors on the login page have no token yet,
    and enforcing auth would drop the most critical class of errors.
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
    """Receive a frontend error report (anonymous allowed, rate limited by IP)"""
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
    """List frontend error reports (admin only)"""
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
    """Delete a single error record (admin only)"""
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
    """Clear all frontend error records (admin only)"""
    if current_user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="只有管理员可以操作")
    count = db.query(ClientError).delete(synchronize_session=False)
    db.commit()
    return {"message": f"已清空 {count} 条记录", "deleted": count}
