"""
Follow-up reminders and schedule

Background: follow-up records (FollowUp) already store `next_follow_up_at`, but an
instant notification is only sent on the next follow-up; salesmen have no "who
should I contact today" to-do view, so follow-ups get missed.

This module provides:
- Pending follow-up schedule queries (today/overdue/this week)
- Automatic reminders for overdue follow-ups (triggered periodically by the scheduler)
"""
import logging
from datetime import datetime, timedelta

from utils.timeutil import utcnow

logger = logging.getLogger(__name__)


def _naive(dt: datetime | None) -> datetime | None:
    """Normalize to naive UTC to avoid aware/naive comparison errors"""
    if dt is None:
        return None
    return dt.replace(tzinfo=None) if dt.tzinfo is not None else dt


def get_pending_follow_ups(
    db,
    user: dict,
    scope: str = "today",
) -> dict[str, list[dict]]:
    """Query the pending follow-up schedule.

    scope:
        today   — due today (overdue included)
        overdue — overdue only
        week    — within the next 7 days

    Data scope: salesmen see only their own customers; admin/reviewer see all.

    Implementation note: `next_follow_up_at` lives on follow-up records and one
    customer may have many historical records; only the **latest** record's
    next_follow_up_at represents the current to-do, so take the latest record per customer.
    """
    from sqlalchemy import func

    from models import Customer, FollowUp

    now = utcnow()
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    today_end = today_start + timedelta(days=1)

    if scope == "overdue":
        time_filter = (FollowUp.next_follow_up_at < now,)
    elif scope == "week":
        time_filter = (FollowUp.next_follow_up_at >= now,
                       FollowUp.next_follow_up_at < now + timedelta(days=7))
    else:  # today: due today (including earlier today, i.e. overdue counts too)
        time_filter = (FollowUp.next_follow_up_at < today_end,)

    # Take the follow-up record with the max id per customer (i.e. the latest)
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

    # Data scope
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
        from utils.masking import mask_phone, should_mask_customer
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


def get_follow_up_summary(db, user: dict) -> dict:
    """Pending follow-up summary (for workbench cards)"""
    overdue = get_pending_follow_ups(db, user, "overdue")
    today = get_pending_follow_ups(db, user, "today")
    week = get_pending_follow_ups(db, user, "week")
    return {
        "overdue": overdue["total"],
        "today": today["total"],
        "week": week["total"],
    }


def send_overdue_follow_up_reminders(db) -> int:
    """Push overdue follow-up reminders to salesmen (called by the scheduler; at most one reminder per customer per day).

    Returns the number of reminders sent.
    """
    from models import Customer, FollowUp, Notification
    from routers.notifications import create_notification

    now = utcnow()
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
        # Dedup: skip if an overdue reminder for this customer was already sent today
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
