import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import desc
from sqlalchemy.orm import Session

from auth import get_current_user
from database import get_db
from models import Notification, User
from schemas import NotificationListResponse

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/notifications", tags=["消息通知"])


@router.get("/", response_model=NotificationListResponse)
async def get_notifications(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    user_id = current_user.get("id")
    
    query = db.query(Notification).filter(Notification.user_id == user_id)
    
    total = query.count()
    unread_count = query.filter(Notification.is_read == False).count()
    
    notifications = (
        query.order_by(desc(Notification.created_at))
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    
    return {
        "items": notifications,
        "total": total,
        "unread_count": unread_count,
    }


@router.post("/read/{notification_id}")
async def mark_as_read(
    notification_id: int,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    user_id = current_user.get("id")
    
    notification = db.query(Notification).filter(
        Notification.id == notification_id,
        Notification.user_id == user_id
    ).first()
    
    if not notification:
        raise HTTPException(status_code=404, detail="通知不存在")
    
    notification.is_read = True
    db.commit()
    
    return {"message": "标记为已读"}


@router.post("/read-all")
async def mark_all_as_read(
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    user_id = current_user.get("id")
    
    db.query(Notification).filter(
        Notification.user_id == user_id,
        Notification.is_read == False
    ).update({"is_read": True})
    
    db.commit()
    
    return {"message": "全部标记为已读"}


@router.get("/unread-count")
async def get_unread_count(
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    user_id = current_user.get("id")
    
    count = db.query(Notification).filter(
        Notification.user_id == user_id,
        Notification.is_read == False
    ).count()
    
    return {"count": count}


@router.delete("/clear-read")
async def clear_read_notifications(
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Clear all read notifications of the current user (prevents the notification list from growing unbounded). Note: must be declared before /{notification_id}, otherwise it gets shadowed by the dynamic route."""
    user_id = current_user.get("id")
    deleted = db.query(Notification).filter(
        Notification.user_id == user_id,
        Notification.is_read == True,
    ).delete(synchronize_session=False)
    db.commit()
    return {"message": f"已清理 {deleted} 条已读通知", "deleted": deleted}


@router.delete("/{notification_id}")
async def delete_notification(
    notification_id: int,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Delete a single notification (only the owner's own notifications)"""
    user_id = current_user.get("id")
    notification = db.query(Notification).filter(
        Notification.id == notification_id,
        Notification.user_id == user_id,
    ).first()
    if not notification:
        raise HTTPException(status_code=404, detail="通知不存在")
    db.delete(notification)
    db.commit()
    return {"message": "已删除"}


def create_notification(
    db: Session,
    user_id: int,
    title: str,
    content: str,
    type: str,
    related_type: str = None,
    related_id: int = None,
):
    """Utility: create a notification. Only adds to the session without committing — the caller
    commits, preserving business atomicity.

    Also pushes asynchronously to external channels (email/Webhook) so users receive
    important reminders without logging in. Silently skipped when external channels are
    unconfigured; delivery failures do not affect in-app notifications.
    """
    notification = Notification(
        user_id=user_id,
        title=title,
        content=content,
        type=type,
        related_type=related_type,
        related_id=related_id,
    )
    db.add(notification)

    # External channel push (background thread; failures do not affect business)
    try:
        from utils.notify_channels import notify_external
        user = db.query(User).filter(User.id == user_id).first()
        notify_external(
            notify_type=type,
            title=title,
            content=content,
            email=getattr(user, "email", None) if user else None,
        )
    except Exception as e:
        # External push failure does not affect in-app notifications, but a silent pass would
        # make "configured yet never delivered" impossible to troubleshoot
        logger.warning(f"外部通知推送失败（站内通知已创建）: {e}")

    return notification
