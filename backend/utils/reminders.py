"""
运营催办：跟进逾期、审核 SLA、申报截止

这些提醒此前要么没接到调度器（跟进逾期），要么配置项 sla_hours_before_review
从未被写入任何字段。调度器每轮调用 send_operational_reminders()。
同一对象同一类型每天只提醒一次，避免轰炸。
"""
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from models import Application, Customer, Material, Notification, User
from routers.notifications import create_notification
from enums import AuditStatus
from utils.follow_up_schedule import send_overdue_follow_up_reminders
from utils.workbench import PENDING_REVIEW_STATUSES, IN_PROGRESS_STATUSES, _naive

logger = logging.getLogger(__name__)


def _today_start() -> datetime:
    # Notification.created_at 以 aware UTC 写入，去重比较需使用 aware 时间
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
    """审核 SLA 已超时：通知分配审核员（未分配则通知全部审核员）+ 管理员。

    只催仍有待审核材料的批次，避免材料已全部审完还反复提醒。
    """
    now = datetime.utcnow()
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
    """申报截止：已逾期或 3 天内到期，通知归属业务员 + 管理员。"""
    now = datetime.utcnow()
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
    """调度器入口：跟进逾期 + 审核 SLA + 申报截止。"""
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
