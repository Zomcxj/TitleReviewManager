"""
Material return-for-revision statistics

Business value: which materials get returned most often is the key clue to raising
approval rates. The stats can feed back to salesmen for prevention (e.g. if
"performance achievements" has the highest return rate, it deserves extra checks
before upload), and also help assess how well each salesman prepares materials.
"""
import logging
from datetime import timedelta

from utils.timeutil import utcnow

logger = logging.getLogger(__name__)


def get_rejection_stats(
    db,
    days: int | None = 90,
    salesman_id: int | None = None,
) -> dict:
    """Return-for-revision statistics by material.

    Args:
        days: look back this many days (None means all)
        salesman_id: only customers under this salesman (None means all)

    Returns:
        {
          "total_reviews": total reviews,
          "total_rejected": total returned,
          "reject_rate": return rate,
          "by_category": [{category, rejected, total, rate}],   # by material category
          "by_issue_type": [{issue_type, count, rate}],          # by issue type
          "by_salesman": [{salesman_id, name, rejected, total, rate}],  # by salesman
          "trend": [{date, rejected}],                           # trend over the last N days
        }
    """
    from sqlalchemy import func

    from models import Application, Customer, Material, Review, User

    since = None
    if days:
        since = utcnow() - timedelta(days=days)

    # Base query: material-level review records (excluding application-level batch reviews)
    base = (
        db.query(Review, Material, Application, Customer)
        .join(Material, Review.material_id == Material.id)
        .join(Application, Review.application_id == Application.id)
        .join(Customer, Application.customer_id == Customer.id)
        .filter(Review.result == "退回", Customer.is_deleted == False)  # noqa: E712
    )
    if since:
        base = base.filter(Review.created_at >= since)
    if salesman_id:
        base = base.filter(Customer.assigned_salesman_id == salesman_id)

    rejected_rows = base.all()

    # Total reviews (approved included) used to compute the return rate
    total_q = (
        db.query(func.count(Review.id))
        .join(Material, Review.material_id == Material.id)
        .join(Application, Review.application_id == Application.id)
        .join(Customer, Application.customer_id == Customer.id)
        .filter(Customer.is_deleted == False)  # noqa: E712
    )
    if since:
        total_q = total_q.filter(Review.created_at >= since)
    if salesman_id:
        total_q = total_q.filter(Customer.assigned_salesman_id == salesman_id)
    total_reviews = total_q.scalar() or 0
    total_rejected = len(rejected_rows)

    # By material category
    cat_rejected: dict[str, int] = {}
    cat_total: dict[str, int] = {}
    all_q = (
        db.query(Material.category, func.count(Review.id))
        .join(Material, Review.material_id == Material.id)
        .join(Application, Review.application_id == Application.id)
        .join(Customer, Application.customer_id == Customer.id)
        .filter(Customer.is_deleted == False)  # noqa: E712
    )
    if since:
        all_q = all_q.filter(Review.created_at >= since)
    if salesman_id:
        all_q = all_q.filter(Customer.assigned_salesman_id == salesman_id)
    for cat, cnt in all_q.group_by(Material.category).all():
        cat_total[cat] = cnt
    for _r, m, _a, _c in rejected_rows:
        cat_rejected[m.category] = cat_rejected.get(m.category, 0) + 1

    by_category = []
    for cat, total in sorted(cat_total.items(), key=lambda x: -x[1]):
        rej = cat_rejected.get(cat, 0)
        by_category.append({
            "category": cat,
            "total": total,
            "rejected": rej,
            "rate": round(rej / total * 100, 1) if total else 0.0,
        })

    # By issue type
    issue_count: dict[str, int] = {}
    for r, _m, _a, _c in rejected_rows:
        key = r.issue_type or "未分类"
        issue_count[key] = issue_count.get(key, 0) + 1
    by_issue_type = [
        {"issue_type": k, "count": v, "rate": round(v / total_rejected * 100, 1) if total_rejected else 0.0}
        for k, v in sorted(issue_count.items(), key=lambda x: -x[1])
    ]

    # By salesman
    sales_rejected: dict[int, int] = {}
    sales_total: dict[int, int] = {}
    for _r, _m, _a, c in rejected_rows:
        sid = c.assigned_salesman_id
        if sid:
            sales_rejected[sid] = sales_rejected.get(sid, 0) + 1

    sales_total_q = (
        db.query(Customer.assigned_salesman_id, func.count(Review.id))
        .join(Application, Application.customer_id == Customer.id)
        .join(Review, Review.application_id == Application.id)
        .join(Material, Review.material_id == Material.id)
        .filter(Customer.is_deleted == False)  # noqa: E712
    )
    if since:
        sales_total_q = sales_total_q.filter(Review.created_at >= since)
    for sid, cnt in sales_total_q.group_by(Customer.assigned_salesman_id).all():
        if sid:
            sales_total[sid] = cnt

    name_map = {u.id: (u.real_name or u.username) for u in db.query(User).all()}
    by_salesman = []
    for sid, total in sorted(sales_total.items(), key=lambda x: -sales_rejected.get(x[0], 0)):
        rej = sales_rejected.get(sid, 0)
        by_salesman.append({
            "salesman_id": sid,
            "name": name_map.get(sid, f"用户{sid}"),
            "total": total,
            "rejected": rej,
            "rate": round(rej / total * 100, 1) if total else 0.0,
        })

    # Trend (last 30 days, or at most 30 days within the given window)
    trend_days = min(days or 30, 30)
    trend_start = utcnow() - timedelta(days=trend_days - 1)
    daily: dict[str, int] = {}
    for r, _m, _a, _c in rejected_rows:
        created = r.created_at
        if created is None:
            continue
        if created.tzinfo is not None:
            created = created.replace(tzinfo=None)
        if created >= trend_start.replace(hour=0, minute=0, second=0, microsecond=0):
            key = created.strftime("%Y-%m-%d")
            daily[key] = daily.get(key, 0) + 1

    trend = []
    for i in range(trend_days):
        d = (trend_start + timedelta(days=i)).strftime("%Y-%m-%d")
        trend.append({"date": d, "rejected": daily.get(d, 0)})

    return {
        "period_days": days,
        "total_reviews": total_reviews,
        "total_rejected": total_rejected,
        "reject_rate": round(total_rejected / total_reviews * 100, 1) if total_reviews else 0.0,
        "by_category": by_category,
        "by_issue_type": by_issue_type,
        "by_salesman": by_salesman,
        "trend": trend,
    }
