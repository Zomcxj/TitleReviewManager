"""
今日待办工作台

把散落的跟进逾期、内部审核积压、申报截止、待收款，收敛成一个按角色过滤的
待办接口。看板此前只有统计数字，业务员/审核员打开后不知道今天该先处理谁。
"""
from datetime import datetime, timedelta

from sqlalchemy import func
from sqlalchemy.orm import Session

from enums import ApplicationStatus, AuditStatus, PaymentStatus
from models import Application, Customer, Material, User
from utils.follow_up_schedule import get_pending_follow_ups
from utils.system_config import get_config
from utils.timeutil import utcnow

PENDING_REVIEW_STATUSES = (
    ApplicationStatus.COMPLETED.value,
    ApplicationStatus.SUPPLEMENT.value,
    ApplicationStatus.REAPPLY.value,
)

IN_PROGRESS_STATUSES = (
    ApplicationStatus.INITIAL.value,
    ApplicationStatus.SUPPLEMENT.value,
    ApplicationStatus.COMPLETED.value,
    ApplicationStatus.SUBMITTED.value,
    ApplicationStatus.REVISE.value,
    ApplicationStatus.REAPPLY.value,
)


def _naive(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    return dt.replace(tzinfo=None) if dt.tzinfo is not None else dt


def _user_id(user: dict) -> int | None:
    return (user or {}).get("user_id") or (user or {}).get("id")


def _hours_overdue(deadline: datetime | None, now: datetime) -> float | None:
    due = _naive(deadline)
    if not due:
        return None
    delta = now - due
    hours = round(delta.total_seconds() / 3600, 1)
    return hours if hours > 0 else 0.0


def _hours_remaining(deadline: datetime | None, now: datetime) -> float | None:
    due = _naive(deadline)
    if not due:
        return None
    delta = due - now
    hours = round(delta.total_seconds() / 3600, 1)
    return hours


def _salesman_scope(query, user: dict, customer_alias=Customer):
    role = (user or {}).get("role")
    if role == "salesman":
        return query.filter(customer_alias.assigned_salesman_id == _user_id(user))
    return query


def _pending_material_counts(db: Session, application_ids: list[int]) -> dict[int, int]:
    if not application_ids:
        return {}
    rows = (
        db.query(Material.application_id, func.count(Material.id))
        .filter(
            Material.application_id.in_(application_ids),
            Material.audit_status == AuditStatus.PENDING.value,
        )
        .group_by(Material.application_id)
        .all()
    )
    return dict(rows)


def _salesman_names(db: Session, ids: set[int]) -> dict[int, str]:
    ids = {i for i in ids if i}
    if not ids:
        return {}
    rows = db.query(User.id, User.real_name, User.username).filter(User.id.in_(ids)).all()
    return {row.id: (row.real_name or row.username) for row in rows}


def list_pending_reviews(
    db: Session,
    user: dict,
    status: str | None = None,
    limit: int = 100,
) -> dict:
    """内部待审核队列。

    口径：批次处于「完成资料 / 资料补充 / 二次申报」，且存在待审核材料。
    审核员/管理员看全部；业务员只看名下客户（便于对照退回补件进度）。
    """
    now = utcnow()
    query = (
        db.query(Application, Customer)
        .join(Customer, Customer.id == Application.customer_id)
        .filter(
            Application.is_deleted == False,  # noqa: E712
            Customer.is_deleted == False,  # noqa: E712
            Application.status.in_(PENDING_REVIEW_STATUSES),
        )
    )
    if status:
        if status not in PENDING_REVIEW_STATUSES:
            return {"items": [], "total": 0}
        query = query.filter(Application.status == status)
    query = _salesman_scope(query, user)

    rows = query.order_by(
        Application.review_sla_deadline.is_(None),
        Application.review_sla_deadline.asc(),
        Application.updated_at.asc(),
    ).limit(max(limit, 1) * 3).all()

    app_ids = [app.id for app, _ in rows]
    pending_counts = _pending_material_counts(db, app_ids)
    salesman_ids = {customer.assigned_salesman_id for _, customer in rows}
    names = _salesman_names(db, salesman_ids)

    items = []
    for app, customer in rows:
        pending = pending_counts.get(app.id, 0)
        if pending <= 0:
            continue
        due = _naive(app.review_sla_deadline)
        remaining = _hours_remaining(due, now)
        overdue_hours = _hours_overdue(due, now)
        items.append({
            "application_id": app.id,
            "customer_id": customer.id,
            "customer_name": customer.name,
            "batch_number": app.batch_number,
            "status": app.status,
            "professional_category": app.professional_category,
            "title_level": app.title_level,
            "pending_materials": pending,
            "assigned_salesman_id": customer.assigned_salesman_id,
            "assigned_salesman_name": names.get(customer.assigned_salesman_id, "未分配"),
            "assigned_reviewer_id": app.assigned_reviewer_id,
            "review_sla_deadline": due.isoformat() if due else None,
            "hours_remaining": remaining,
            "overdue": bool(due and due < now),
            "overdue_hours": overdue_hours if due and due < now else 0,
        })
        if len(items) >= limit:
            break

    return {"items": items, "total": len(items)}


def list_upcoming_deadlines(
    db: Session,
    user: dict,
    days: int = 7,
    limit: int = 50,
) -> dict:
    """申报截止：已逾期 + 未来 N 天内，排除终态。"""
    now = utcnow()
    until = now + timedelta(days=days)
    query = (
        db.query(Application, Customer)
        .join(Customer, Customer.id == Application.customer_id)
        .filter(
            Application.is_deleted == False,  # noqa: E712
            Customer.is_deleted == False,  # noqa: E712
            Application.cycle_deadline.isnot(None),
            Application.cycle_deadline < until,
            Application.status.in_(IN_PROGRESS_STATUSES),
        )
    )
    query = _salesman_scope(query, user)
    rows = query.order_by(Application.cycle_deadline.asc()).limit(limit).all()
    names = _salesman_names(db, {c.assigned_salesman_id for _, c in rows})

    items = []
    for app, customer in rows:
        due = _naive(app.cycle_deadline)
        remaining = _hours_remaining(due, now)
        items.append({
            "application_id": app.id,
            "customer_id": customer.id,
            "customer_name": customer.name,
            "batch_number": app.batch_number,
            "status": app.status,
            "cycle_year": app.cycle_year,
            "cycle_deadline": due.isoformat() if due else None,
            "hours_remaining": remaining,
            "overdue": bool(due and due < now),
            "assigned_salesman_id": customer.assigned_salesman_id,
            "assigned_salesman_name": names.get(customer.assigned_salesman_id, "未分配"),
        })
    return {"items": items, "total": len(items)}


def list_pending_payments_brief(db: Session, user: dict, limit: int = 20) -> dict:
    """待收款摘要（工作台用，不含完整财务明细）。"""
    role = (user or {}).get("role")
    if role not in ("admin", "salesman"):
        return {"items": [], "total": 0, "total_unpaid": 0.0}

    query = (
        db.query(Application, Customer)
        .join(Customer, Customer.id == Application.customer_id)
        .filter(
            Application.is_deleted == False,  # noqa: E712
            Customer.is_deleted == False,  # noqa: E712
            Application.fee_amount.isnot(None),
            Application.payment_status.in_([
                PaymentStatus.UNPAID.value,
                PaymentStatus.PARTIAL.value,
            ]),
        )
    )
    query = _salesman_scope(query, user)
    rows = query.all()

    items = []
    for app, customer in rows:
        fee = float(app.fee_amount or 0)
        paid = float(app.paid_amount or 0)
        unpaid = round(max(0.0, fee - paid), 2)
        if unpaid <= 0:
            continue
        items.append({
            "application_id": app.id,
            "customer_id": customer.id,
            "customer_name": customer.name,
            "batch_number": app.batch_number,
            "fee_amount": fee,
            "paid_amount": paid,
            "unpaid_amount": unpaid,
            "payment_status": app.payment_status,
        })
    items.sort(key=lambda x: x["unpaid_amount"], reverse=True)
    clipped = items[:limit]
    return {
        "items": clipped,
        "total": len(items),
        "total_unpaid": round(sum(x["unpaid_amount"] for x in items), 2),
    }


def get_workbench(db: Session, user: dict) -> dict:
    """按角色返回今日待办。"""
    role = (user or {}).get("role") or ""
    follow_ups = get_pending_follow_ups(db, user, "today")
    overdue_follow_ups = get_pending_follow_ups(db, user, "overdue")
    reviews = list_pending_reviews(db, user, limit=30)
    deadlines = list_upcoming_deadlines(db, user, days=7, limit=30)
    payments = list_pending_payments_brief(db, user, limit=10)

    overdue_reviews = sum(1 for item in reviews["items"] if item.get("overdue"))
    overdue_deadlines = sum(1 for item in deadlines["items"] if item.get("overdue"))

    summary = {
        "follow_ups_today": follow_ups["total"],
        "follow_ups_overdue": overdue_follow_ups["total"],
        "pending_reviews": reviews["total"],
        "overdue_reviews": overdue_reviews,
        "upcoming_deadlines": deadlines["total"],
        "overdue_deadlines": overdue_deadlines,
        "pending_payments": payments["total"],
        "pending_unpaid_amount": payments.get("total_unpaid", 0),
    }
    if role == "reviewer":
        summary["pending_payments"] = 0
        summary["pending_unpaid_amount"] = 0
        payments = {"items": [], "total": 0, "total_unpaid": 0.0}

    return {
        "role": role,
        "generated_at": utcnow().isoformat(),
        "summary": summary,
        "follow_ups": follow_ups["items"][:20],
        "reviews": reviews["items"],
        "deadlines": deadlines["items"],
        "payments": payments["items"],
    }


def mark_review_sla_started(db: Session, app: Application) -> None:
    """批次进入内部待审（完成资料）时写入审核 SLA。已有截止时间则不覆盖。"""
    if not app or app.review_sla_deadline:
        return
    hours = get_config(db, "sla_hours_before_review") or 48
    try:
        hours = int(hours)
    except (TypeError, ValueError):
        hours = 48
    app.review_sla_deadline = utcnow() + timedelta(hours=max(hours, 1))


def clear_review_sla(app: Application) -> None:
    if app is not None:
        app.review_sla_deadline = None
