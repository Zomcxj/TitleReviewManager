"""
Operational reminders: overdue follow-ups, review SLA, application deadlines

Previously these reminders either were never wired to the scheduler (overdue
follow-ups) or the sla_hours_before_review config was never written to any field.
The scheduler calls send_operational_reminders() each round. At most one reminder
per object per type per day, to avoid bombardment.
"""
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from enums import AuditStatus
from models import Application, Customer, Material, Notification, User
from routers.notifications import create_notification
from utils.follow_up_schedule import send_overdue_follow_up_reminders
from utils.timeutil import utcnow
from utils.workbench import IN_PROGRESS_STATUSES, PENDING_REVIEW_STATUSES, _naive

logger = logging.getLogger(__name__)


def _today_start() -> datetime:
    # Notification.created_at is stored as aware UTC; dedup comparisons need aware datetimes
    now = datetime.now(timezone.utc)
    return now.replace(hour=0, minute=0, second=0, microsecond=0)


def _already_notified(db: Session, *, user_id: int, ntype: str, related_type: str, related_id: int) -> bool:
    return db.query(Notification).filter(
        Notification.user_id == user_id,
        Notification.type == ntype,
        Notification.related_type == related_type,
        Notification.related_id == related_id,
        Notification.created_at >= _today_start(),
    ).first() is not None


def _notify_admins(db: Session, *, title: str, content: str, ntype: str, related_type: str, related_id: int) -> int:
    sent = 0
    for admin in db.query(User).filter(User.role == "admin", User.is_deleted == False).all():  # noqa: E712
        if _already_notified(db, user_id=admin.id, ntype=ntype, related_type=related_type, related_id=related_id):
            continue
        create_notification(
            db=db, user_id=admin.id, title=title, content=content,
            type=ntype, related_type=related_type, related_id=related_id,
        )
        sent += 1
    return sent


def send_review_sla_reminders(db: Session) -> int:
    """Review SLA exceeded: notify the assigned reviewer (or all reviewers if unassigned) + admins.

    Only nudge applications that still have materials pending review, avoiding
    repeated reminders after everything has already been reviewed.
    """
    now = utcnow()
    pending_app_ids = {
        row[0] for row in db.query(Material.application_id)
        .filter(Material.audit_status == AuditStatus.PENDING.value)
        .distinct()
        .all()
    }
    if not pending_app_ids:
        return 0
    rows = (
        db.query(Application, Customer)
        .join(Customer, Customer.id == Application.customer_id)
        .filter(
            Application.is_deleted == False,  # noqa: E712
            Customer.is_deleted == False,  # noqa: E712
            Application.id.in_(pending_app_ids),
            Application.status.in_(PENDING_REVIEW_STATUSES),
            Application.review_sla_deadline.isnot(None),
            Application.review_sla_deadline < now,
        )
        .all()
    )
    sent = 0
    reviewers = None
    for app, customer in rows:
        hours = int((now - _naive(app.review_sla_deadline)).total_seconds() // 3600)
        title = "审核时效已超时"
        content = (
            f"客户 {customer.name} 的批次 {app.batch_number or app.id} "
            f"待审核已超时 {hours} 小时，请尽快处理"
        )
        recipients = []
        if app.assigned_reviewer_id:
            recipients.append(app.assigned_reviewer_id)
        else:
            if reviewers is None:
                reviewers = [
                    u.id for u in db.query(User).filter(
                        User.role == "reviewer", User.is_deleted == False  # noqa: E712
                    ).all()
                ]
            recipients.extend(reviewers)
        for uid in set(recipients):
            if _already_notified(db, user_id=uid, ntype="review_sla_overdue",
                                 related_type="application", related_id=app.id):
                continue
            create_notification(
                db=db, user_id=uid, title=title, content=content,
                type="review_sla_overdue", related_type="application", related_id=app.id,
            )
            sent += 1
        sent += _notify_admins(
            db, title=title, content=content,
            ntype="review_sla_overdue", related_type="application", related_id=app.id,
        )
    return sent


def send_cycle_deadline_reminders(db: Session) -> int:
    """Application deadline: overdue or due within 3 days; notify the owning salesman + admins."""
    now = utcnow()
    soon = now + timedelta(days=3)
    rows = (
        db.query(Application, Customer)
        .join(Customer, Customer.id == Application.customer_id)
        .filter(
            Application.is_deleted == False,  # noqa: E712
            Customer.is_deleted == False,  # noqa: E712
            Application.cycle_deadline.isnot(None),
            Application.cycle_deadline < soon,
            Application.status.in_(IN_PROGRESS_STATUSES),
        )
        .all()
    )
    sent = 0
    for app, customer in rows:
        due = _naive(app.cycle_deadline)
        overdue = due and due < now
        ntype = "cycle_deadline_overdue" if overdue else "cycle_deadline_warning"
        if overdue:
            days = max((now - due).days, 0)
            title = "申报截止已逾期"
            content = f"客户 {customer.name} 的批次 {app.batch_number or app.id} 申报截止已逾期 {days} 天"
        else:
            days = max((due - now).days, 0)
            title = "申报即将截止"
            content = f"客户 {customer.name} 的批次 {app.batch_number or app.id} 将在 {days} 天内截止，请尽快报送"
        recipients = []
        if customer.assigned_salesman_id:
            recipients.append(customer.assigned_salesman_id)
        for uid in recipients:
            if _already_notified(db, user_id=uid, ntype=ntype,
                                 related_type="application", related_id=app.id):
                continue
            create_notification(
                db=db, user_id=uid, title=title, content=content,
                type=ntype, related_type="application", related_id=app.id,
            )
            sent += 1
        sent += _notify_admins(
            db, title=title, content=content,
            ntype=ntype, related_type="application", related_id=app.id,
        )
    return sent


def send_operational_reminders() -> dict:
    """Scheduler entry point: overdue follow-ups + review SLA + application deadlines."""
    from database import SessionLocal

    db = SessionLocal()
    result = {"follow_up": 0, "review_sla": 0, "cycle_deadline": 0}
    try:
        result["follow_up"] = send_overdue_follow_up_reminders(db)
        result["review_sla"] = send_review_sla_reminders(db)
        result["cycle_deadline"] = send_cycle_deadline_reminders(db)
        db.commit()
    except Exception:
        db.rollback()
        logger.exception("运营催办执行失败")
        raise
    finally:
        db.close()
    return result
