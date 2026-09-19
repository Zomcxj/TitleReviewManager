"""
跟进提醒与日程

背景：跟进记录（FollowUp）已能记录 `next_follow_up_at`，但只在下一次跟进时
发一条即时通知，业务员没有"今天该联系谁"的待办视图，容易漏跟。

这里提供：
- 待跟进日程查询（今天/逾期/本周）
- 逾期未跟进的自动提醒（由调度器定期触发）
"""
import logging
from datetime import datetime, timedelta
from typing import Optional, List, Dict

logger = logging.getLogger(__name__)


def _naive(dt: Optional[datetime]) -> Optional[datetime]:
    """统一为 naive UTC，避免 aware/naive 比较报错"""
    if dt is None:
        return None
    return dt.replace(tzinfo=None) if dt.tzinfo is not None else dt


def get_pending_follow_ups(
    db,
    user: dict,
    scope: str = "today",
) -> Dict[str, List[Dict]]:
    """查询待跟进日程。

    scope:
        today  —— 今天到期（含已逾期）
        overdue —— 仅已逾期
        week   —— 未来 7 天内

    数据范围：业务员仅自己名下客户；admin/reviewer 可见全部。

    实现说明：`next_follow_up_at` 存在跟进记录上，同一客户可能有多条历史记录，
    只有**最新一条**的 next_follow_up_at 才代表当前待办，因此按客户取最新记录。
    """
    from sqlalchemy import func
    from models import FollowUp, Customer

    now = datetime.utcnow()
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    today_end = today_start + timedelta(days=1)

    if scope == "overdue":
        time_filter = (FollowUp.next_follow_up_at < now,)
    elif scope == "week":
        time_filter = (FollowUp.next_follow_up_at >= now,
                       FollowUp.next_follow_up_at < now + timedelta(days=7))
    else:  # today：今天到期（含今天已过时点的，即 overdue 也算）
        time_filter = (FollowUp.next_follow_up_at < today_end,)

    # 每个客户取 id 最大的那条跟进记录（即最新）
    latest_subq = (
        db.query(
            FollowUp.customer_id.label("cid"),
            func.max(FollowUp.id).label("max_id"),
        )
        .group_by(FollowUp.customer_id)
        .subquery()
    )

    query = (
        db.query(FollowUp, Customer)
        .join(latest_subq, FollowUp.id == latest_subq.c.max_id)
        .join(Customer, Customer.id == FollowUp.customer_id)
        .filter(
            FollowUp.next_follow_up_at.isnot(None),
            Customer.is_deleted == False,  # noqa: E712
            *time_filter,
        )
    )

    # 数据范围
    role = (user or {}).get("role")
    if role == "salesman":
        uid = (user or {}).get("user_id") or (user or {}).get("id")
        query = query.filter(Customer.assigned_salesman_id == uid)
    elif role not in ("admin", "reviewer"):
        return {"items": [], "total": 0, "scope": scope}

    rows = query.order_by(FollowUp.next_follow_up_at.asc()).limit(200).all()

    items = []
    for fu, customer in rows:
        due = _naive(fu.next_follow_up_at)
        phone = customer.phone
        from utils.masking import should_mask_customer, mask_phone
        if should_mask_customer(user, customer):
            phone = mask_phone(phone)
        items.append({
            "customer_id": customer.id,
            "customer_name": customer.name,
            "phone": phone,
            "assigned_salesman_id": customer.assigned_salesman_id,
            "follow_up_id": fu.id,
            "follow_up_type": fu.follow_up_type,
            "last_content": (fu.content or "")[:100],
            "next_follow_up_at": due.isoformat() if due else None,
            "overdue": bool(due and due < now),
            "overdue_days": (now - due).days if due and due < now else 0,
        })

    return {"items": items, "total": len(items), "scope": scope}


def get_follow_up_summary(db, user: dict) -> Dict:
    """待跟进汇总（用于工作台卡片）"""
    overdue = get_pending_follow_ups(db, user, "overdue")
    today = get_pending_follow_ups(db, user, "today")
    week = get_pending_follow_ups(db, user, "week")
    return {
        "overdue": overdue["total"],
        "today": today["total"],
        "week": week["total"],
    }


def send_overdue_follow_up_reminders(db) -> int:
    """向业务员推送逾期跟进提醒（由调度器调用，同一客户每天只提醒一次）。

    返回发送的提醒条数。
    """
    from models import FollowUp, Customer, Notification, User
    from routers.notifications import create_notification

    now = datetime.utcnow()
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)

    from sqlalchemy import func
    latest_subq = (
        db.query(
            FollowUp.customer_id.label("cid"),
            func.max(FollowUp.id).label("max_id"),
        )
        .group_by(FollowUp.customer_id)
        .subquery()
    )

    rows = (
        db.query(FollowUp, Customer)
        .join(latest_subq, FollowUp.id == latest_subq.c.max_id)
        .join(Customer, Customer.id == FollowUp.customer_id)
        .filter(
            FollowUp.next_follow_up_at.isnot(None),
            FollowUp.next_follow_up_at < now,
            Customer.is_deleted == False,  # noqa: E712
            Customer.assigned_salesman_id.isnot(None),
        )
        .all()
    )

    sent = 0
    for fu, customer in rows:
        salesman_id = customer.assigned_salesman_id
        # 去重：今天已就该客户发过逾期提醒则跳过
        exists = db.query(Notification).filter(
            Notification.user_id == salesman_id,
            Notification.type == "follow_up_overdue",
            Notification.related_type == "customer",
            Notification.related_id == customer.id,
            Notification.created_at >= today_start,
        ).first()
        if exists:
            continue

        due = _naive(fu.next_follow_up_at)
        days = (now - due).days if due else 0
        create_notification(
            db=db,
            user_id=salesman_id,
            title="跟进已逾期",
            content=f"客户 {customer.name} 的计划跟进时间已逾期 {days} 天，请尽快联系",
            type="follow_up_overdue",
            related_type="customer",
            related_id=customer.id,
        )
        sent += 1

    if sent:
        db.commit()
    return sent
