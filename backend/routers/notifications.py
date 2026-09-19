from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import desc
from database import get_db
from models import Notification, User
from schemas import NotificationListResponse
from auth import get_current_user

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
    """清理本人所有已读通知（避免通知列表无限膨胀）。注意：必须声明在 /{notification_id} 之前，否则会被动态路由遮蔽。"""
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
    """删除单条通知（仅本人的通知）"""
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
    """工具函数：创建通知。只加入会话，不提交 —— 由调用方统一 commit，保证业务原子性。

    同时异步推送到外部渠道（邮件/Webhook），让用户不登录也能收到重要提醒。
    外部渠道未配置时静默跳过，发送失败也不影响站内通知。
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

    # 外部渠道推送（后台线程，失败不影响业务）
    try:
        from utils.notify_channels import notify_external
        user = db.query(User).filter(User.id == user_id).first()
        notify_external(
            notify_type=type,
            title=title,
            content=content,
            email=getattr(user, "email", None) if user else None,
        )
    except Exception:
        pass

    return notification
